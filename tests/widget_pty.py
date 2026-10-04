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
# look file brings the built-in colour and a long failure's duration and
# never a greeting or a news line; one text per fallback; bash chains an
# EXIT trap it found. The face (v1.80): awake, every line in the row
# carries its mood's face after the mark, and the resting face stands
# alone above an idle prompt -- only where the blank row is known -- and
# is erased at Enter; Esc r hands the row's height to spark recall; the
# look off, a machine not awake and `spark off` each give the bytes they
# gave before; zsh blinks at an empty line, stands still with text in
# it, sleeps and wakes, and bash's face is still. On a rendered screen the failure
# line sits in the hint row and Esc s replaces it there (v1.72). Then the
# voice keys (v1.70): Esc v lands what a stub `spark voice listen
# --buffer` heard -- a `? ` question on an empty line, beside the words
# at the cursor otherwise -- and runs nothing; the row says it listens,
# nothing heard is one quiet line, a voice that cannot listen says how
# to turn it on; Esc x is `spark voice stop`. Then the alert (v1.81): a
# check row that turned worse is said at the next prompt, once in each
# pane, and its heal only where the warning was shown; a failure line
# goes first, `spark off` is silent, a line that is not clean is
# dropped, the look file is still read; an answer to a paste is
# pleased; and in zsh Ctrl-C at a prompt leaves no resting face.
#
#   widget_pty.py bash home/.config/spark/widget.bash
#   widget_pty.py zsh  home/.config/spark/widget.zsh
#
# widget_pty.py pager: the same pty machinery, 10 rows, around the real
# `spark help` -- long output goes through $PAGER at a terminal, and an
# absent $PAGER falls back to plain output.
#
# widget_pty.py completion <shell> <file>: the same pty machinery around
# the completion file -- `spark awa<TAB>` completes to `awaken`, and
# `spark model gr<TAB>` to a model row's name (the dynamic names, resolved
# offline through a spark symlink into the real repository).

import fcntl
import glob
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
# the voice keys (v1.70): Esc v asks `spark voice listen --buffer` --
# STUB_HEARD is what it heard (empty: nothing, exit 1; STUB_NOVOICE: the
# voice is off, exit 2) -- and Esc x `spark voice stop`; both logged
if [ "$1" = voice ]; then
    printf '%s\n' "$*" >> "${STUB_VOICE:-/dev/null}"
    if [ "$2" = listen ]; then
        [ -n "${STUB_NOVOICE:-}" ] && { echo "spark voice -- the voice is off" >&2; exit 2; }
        [ -n "${STUB_HEARD:-}" ] || exit 1
        printf '%s\n' "$STUB_HEARD"
    fi
    exit 0
fi
# the row's height (v1.59): Esc k keeps its choice through `spark height N`
if [ "$1" = height ]; then
    printf '%s\n' "$2" >> "${STUB_HEIGHT:-/dev/null}"
    exit 0
fi
# the greeting an older widget asked for: a widget that still asks is
# caught by the log (v1.72: nothing is greeted)
if [ "$1" = words ] && [ "$2" = greet ]; then
    printf 'greet\n' >> "${STUB_GREET:-/dev/null}"
    printf 'Good evening.\n'
    exit 0
fi
if [ "$1" = recall ]; then
    # history arrives on stdin; grounding is cli's job, not the stub's --
    # here we hand back two plain lines and one danger-marked line (the
    # `!<TAB>` prefix recall puts on a line that can destroy). The row's
    # height reaches it too (v1.80), logged apart from spark line's
    printf 'SPARK_HINT_ROW=%s\n' "${SPARK_HINT_ROW-}" >> "${STUB_RECALL:-/dev/null}"
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
            os.umask(0o022)            # a common umask: what the shell creates is said against it
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


# the look file as look.content writes it: one switch, SPARK_LOOK, so the
# three parts always carry the same value
FACES = ("FACE_ASLEEP=(-.-)z\nFACE_WAKING=(-o-)\nFACE_IDLE=(o.o)\nFACE_THINKING=(o.O)\nFACE_PLEASED=(^.^)\n"
         "FACE_PUZZLED=(o.?)\nFACE_ALARMED=(O.O)\nFACE_LISTENING=(o.o)~\nFACE_BLINK=(-.-)\nFACE_GLANCE=(.o.)\n")
LOOK_AWAKE = ("AWAKE=yes\nMOTION=on\nCOLOUR=on\nWORDS=on\nHEIGHT=2\nSGR_ACCENT=1\nSGR_MUTED=2\n"
              "SGR_WARN=31\nSGR_OK=32\nSGR_TROUBLE=1;31\nSGR_YOU=\n" + FACES +
              # a value with an escape in it is dropped whole, and one too
              # long or beyond ASCII: the face read before it stays
              "FACE_IDLE=\x1b[2J(x.x)\nFACE_PLEASED=(^.^)(x.x)\nFACE_ALARMED=(Ø.Ø)\n"
              "BLINK=14\nTEMPER=plain\n")
# the frames the widgets draw: the row N up, cleared, then the text
ROW = "\x1b7\x1b[%dA\r\x1b[2K%s\x1b8"
EVERY_FACE = ("(o.o)", "(o.O)", "(^.^)", "(o.?)", "(O.O)", "(-.-)", "(.o.)", "(-o-)")


def living(shell, widget, tmp, env, ok):
    """v1.59, the living prompt: the row's height with a two-line prompt,
    Esc k, then an awake look file -- the built-in colour, a failed
    command's duration, no greeting or news line -- and the fallback
    texts, the same in both shells; bash chains an EXIT trap it found.
    v1.80, the face: beside the mark in every line of the row, alone
    above an idle prompt and gone at Enter; not awake, the look off and
    `spark off` each give the bytes they gave before."""
    state = os.path.join(tmp, "living-state")
    sd = os.path.join(state, "spark")
    os.makedirs(sd)
    look = os.path.join(sd, "look")
    hlog, glog, elog, tlog, rlog = (os.path.join(tmp, n) for n in
                                    ("height.log", "greet.log", "living-env.log", "trap.log", "recall-env.log"))
    env = dict(env, XDG_STATE_HOME=state, STUB_HEIGHT=hlog, STUB_GREET=glog, STUB_ENV=elog, TRAPLOG=tlog,
               STUB_RECALL=rlog)
    with open(look, "w") as f:
        # not awake: the faces are in the file, and none is drawn
        f.write("AWAKE=no\nMOTION=off\nCOLOUR=off\nWORDS=off\nHEIGHT=2\n" + FACES + "BLINK=14\n")
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
        ok(sh.expect("\x1b7\x1b[%dA\r\x1b[2K* spark writes here -- Esc k moves it\x1b8" % n),
           "Esc k: the test line moves to height %d" % n, since()[-300:])
        sh.settle()
    ok(lines(hlog) == ["3", "1", "2"], "Esc k: spark height ran with 3, 1, 2", lines(hlog))

    # asleep: no duration
    sh.send("_SPARK_LONG=1\r")
    sh.expect(prompt)
    since = sh.mark()
    sh.send("sleep 2; sh -c 'exit 3'\r")
    ok(sh.expect("failed (3) -- Esc s asks why", 10), "asleep: a failure line says no duration", since()[-300:])
    sh.expect(prompt)
    sh.settle()
    if shell == "zsh":
        # the failure line is the hint row's: drawn two rows up, at height 2
        ok("\x1b7\x1b[2A\r\x1b[2K* failed (3) -- Esc s asks why\x1b8" in since(),
           "height 2: the failure line is drawn in the hint row", since()[-300:])
    else:
        # bash: the line, then the prompt's own opening newline ends it
        ok(re.search(r"\* failed \(3\) -- Esc s asks why(\x1b\[\?2004h)?\r*\nINFO-LINE", since()) is not None,
           "height 2: the failure line is the prompt's blank row", since()[-300:])

    # not awake: every byte so far is what it was before the face
    ok(not any(f in sh.buf.decode("utf-8", "replace") for f in EVERY_FACE),
       "not awake: no face anywhere, the faces in the look file or not")

    def put(text):
        with open(look, "w", encoding="utf-8") as f:
            f.write(text)
        # newer than the shell's marker, whatever the clock's grain
        stamp[0] += 6
        os.utime(look, (stamp[0], stamp[0]))
    stamp = [time.time()]
    erase = ROW % (2, "")
    if shell == "zsh":
        idle = ROW % (2, "\x1b[1m(o.o)\x1b[0m")
    else:
        # bash: the face, then the prompt's own opening newline ends it
        idle = None
    idle_re = r"\x1b\[1m\(o\.o\)\x1b\[0m(\x1b\[\?2004h)?\r*\nINFO-LINE"

    def idle_seen(text):
        return idle in text if idle else re.search(idle_re, text) is not None

    # awake, after an absence, a news file there: the next prompt says
    # nothing -- no greeting, no news, no fork, no stamp -- and the
    # resting face stands alone in the blank row
    put(LOOK_AWAKE)
    with open(os.path.join(sd, "last-seen"), "w") as f:
        f.write("1000\n")                      # an absence of decades
    old = time.time() - 60
    for m in os.listdir(os.path.join(sd, "widgets")):
        os.utime(os.path.join(sd, "widgets", m), (old, old))
    since = sh.mark()
    sh.send("\r")
    sh.expect(prompt)
    sh.settle()
    seen = since()
    ok("Good evening" not in seen and "not while asleep" not in seen and not lines(glog)
       and lines(os.path.join(sd, "last-seen")) == ["1000"] and not os.path.exists(os.path.join(sd, "news-seen")),
       "awake: no greeting, no news; spark words greet never runs", seen[-300:])
    ok(idle_seen(seen), "awake: the resting face stands alone in the blank row above the prompt", seen[-300:])
    ok("(x.x)" not in seen and "\x1b[2J" not in seen, "awake: a face with an escape in it is dropped", seen[-300:])

    # awake: a failed command that ran long says how long; a quick one
    # not. Enter erases the resting face first; the line has its own
    since = sh.mark()
    sh.send("sleep 2; sh -c 'exit 3'\r")
    ok(sh.expect("failed (3) after ", 10), "awake: a long failure says how long", since()[-300:])
    ok(re.search(r"failed \(3\) after [23] s -- Esc s asks why", since()) is not None,
       "awake: the duration reads N s", since()[-300:])
    sh.expect(prompt)
    sh.settle()
    seen = since()
    ok(erase in seen and seen.index(erase) < seen.index("failed (3)"),
       "awake: Enter erases the resting face, so scrollback keeps none", seen[-400:])
    ok("\x1b[1m* (O.O)\x1b[0m failed (3) after " in seen, "awake: the failure line carries the alarmed face",
       seen[-300:])
    ok(not idle_seen(seen[seen.index("failed (3)"):]), "awake: a failure line keeps the row, no resting face over it",
       seen[-300:])
    since = sh.mark()
    sh.send("sh -c 'exit 4'\r")
    ok(sh.expect("* (O.O)\x1b[0m failed (4) -- Esc s asks why"), "awake: a quick failure says no duration",
       since()[-300:])
    sh.expect(prompt)
    sh.settle()

    # the built-in accent paints the mark and its face; an answer is pleased
    since = sh.mark()
    sh.send("answer-me?\r")
    ok(sh.expect(ROW % (2, "\x1b[1m* (^.^)\x1b[0m Forty-two")),
       "awake: an answer carries the pleased face, in the built-in accent, at height 2", since()[-300:])
    ok("\x1b[1m* (o.O)\x1b[0m " in since(), "awake: the beat before spark line shows the thinking face",
       since()[-300:])
    ok("(^.^)(x.x)" not in since(), "awake: a face past 8 characters is dropped", since()[-300:])
    sh.send("\r")
    sh.expect(prompt)
    sh.settle()
    # a command's hint is the resting face beside the mark; a danger is alarmed
    since = sh.mark()
    sh.send("? list big files\r")
    ok(sh.expect(ROW % (2, "\x1b[1m* (o.o)\x1b[0m A hint about it")), "awake: a hint carries the resting face",
       since()[-300:])
    sh.send("\x15")
    sh.settle()
    since = sh.mark()
    sh.send("? delete it all\r")
    ok(sh.expect(ROW % (2, "\x1b[31m! (O.O) Deletes things -- careful -- read it before Enter\x1b[0m")),
       "awake: a danger line carries the alarmed face, whole in warn", since()[-300:])
    sh.send("\x15")
    sh.settle()
    # awake, Esc v: the row says it listens, with the listening face
    since = sh.mark()
    sh.send("\x1bv")
    ok(sh.expect("\x1b[1m* (o.o)~\x1b[0m listening -- a pause ends it"), "awake: Esc v listens with the listening face",
       since()[-300:])
    ok(sh.expect("heard -- Enter asks it"), "awake: Esc v lands what it heard", since()[-300:])
    sh.send("\x15")
    sh.settle()
    # Esc r: the row's height reaches spark recall
    since = sh.mark()
    sh.send("amend the commit\x1br")
    ok(sh.expect("1/3 -- Esc r for the next"), "awake: Esc r lands a candidate", since()[-300:])
    ok(lines(rlog)[-1:] == ["SPARK_HINT_ROW=2"], "Esc r: spark recall hears SPARK_HINT_ROW=2", lines(rlog))
    sh.send("\x15")
    sh.settle()
    put(LOOK_AWAKE.replace("MOTION=on", "MOTION=auto").replace("COLOUR=on", "COLOUR=auto")
        .replace("WORDS=on", "WORDS=auto"))
    sh.send("export NO_COLOR=1\r")
    sh.expect(prompt)
    sh.settle()
    since = sh.mark()
    sh.send("answer-me?\r")
    ok(sh.expect("\x1b[2K* (^.^) Forty-two") and "\x1b[1m*" not in since(), "awake: NO_COLOR under auto is plain",
       since()[-300:])
    sh.send("\r")
    sh.expect(prompt)

    # one text for each fallback, the same in both shells: puzzled when
    # nothing came, alarmed when no model answers
    since = sh.mark()
    sh.send("answer-empty?\r")
    ok(sh.expect("* (o.?) no answer came"), "fallback: an empty answer says: no answer came", since()[-300:])
    sh.send("\r")
    sh.expect(prompt)
    since = sh.mark()
    sh.send("hostile-empty?\r")
    ok(sh.expect("* (O.O) no model answers"), "fallback: nothing at all says: no model answers", since()[-300:])
    sh.send("\x15")
    sh.settle()
    since = sh.mark()
    sh.send("\x1bs")
    ok(sh.expect("* (o.?) type a question, then Esc s"), "fallback: Esc s on an empty line is puzzled",
       since()[-300:])
    sh.send("\x15")
    sh.settle()
    ok("no brain awake" not in sh.buf.decode("utf-8", "replace"), "fallback: the old text is gone")

    if shell == "zsh":
        # motion, zsh alone: at an empty line the face blinks within its
        # period (BLINK=14: about 5 s) and rests again; with text in the
        # line it stands still; after `spark off` it is gone for good
        plain_idle, blink = ROW % (2, "(o.o)"), ROW % (2, "(-.-)")
        since = sh.mark()
        sh.send("\r")
        ok(sh.expect(plain_idle), "zsh: a fresh prompt draws the resting face", since()[-300:])
        since = sh.mark()
        ok(sh.expect(blink, 8) and sh.expect(blink + plain_idle, 2),
           "zsh: at an empty line the face blinks within its period, one beat, and rests", since()[-300:])
        sh.send("abc")
        sh.settle()
        since = sh.mark()
        sh.read(7.0)
        ok("\x1b7" not in since(), "zsh: with text in the line the face stands still", since()[-300:])
        sh.send("\x15")
        sh.settle()
        open(os.path.join(sd, "off"), "w").close()
        since = sh.mark()
        sh.read(8.0)
        seen = since()
        ok(seen.count(erase) == 1 and not any(f in seen for f in EVERY_FACE),
           "zsh: after spark off the tick erases the face once and draws no more", seen[-300:])
    else:
        # bash: the face is still -- nothing draws while the prompt waits
        since = sh.mark()
        sh.send("\r")
        sh.expect(prompt)
        sh.settle()
        since = sh.mark()
        sh.read(4.0)
        ok(since() == "", "bash: the resting face is still: nothing is drawn while the prompt waits", since()[-300:])
        open(os.path.join(sd, "off"), "w").close()

    # spark off, awake look and all: the bytes are what they were -- no
    # face at the prompt, no failure line, no frame of any kind
    sh.send("\r")
    sh.expect(prompt)
    sh.settle()
    since = sh.mark()
    sh.send("\r")
    sh.expect(prompt)
    sh.send("sh -c 'exit 5'\r")
    sh.expect(prompt)
    sh.send("\r")
    sh.expect(prompt)
    sh.settle()
    seen = since()
    ok("\x1b7" not in seen and "failed" not in seen and not any(f in seen for f in EVERY_FACE),
       "spark off: no face, no failure line, no frame -- the bytes it gave before", seen[-300:])
    os.remove(os.path.join(sd, "off"))

    # the look off on an awake machine (spark look off): the three parts
    # off, the faces still in the file. Every line is the plain one it
    # was, to the byte, and the prompt carries no face
    put(LOOK_AWAKE.replace("MOTION=on", "MOTION=off").replace("COLOUR=on", "COLOUR=off")
        .replace("WORDS=on", "WORDS=off"))
    sh.send("unset NO_COLOR\r")
    sh.expect(prompt)
    sh.settle()
    since = sh.mark()
    sh.send("answer-me?\r")
    ok(sh.expect(ROW % (2, "* Forty-two")), "look off: an answer is the plain line it was", since()[-300:])
    sh.send("\r")
    sh.expect(prompt)
    sh.send("sh -c 'exit 6'\r")
    ok(sh.expect("failed (6) -- Esc s asks why"), "look off: a failure still says so", since()[-300:])
    sh.expect(prompt)
    sh.settle()
    seen = since()
    if shell == "zsh":
        ok(ROW % (2, "* failed (6) -- Esc s asks why") in seen, "look off: the failure line is the plain frame it was",
           seen[-300:])
    else:
        ok(re.search(r"(?<!m)\* failed \(6\) -- Esc s asks why(\x1b\[\?2004h)?\r*\nINFO-LINE", seen) is not None,
           "look off: the failure line is the plain line it was", seen[-300:])
    since2 = sh.mark()
    sh.send("\x1bv")
    ok(sh.expect(ROW % (2, "* listening -- a pause ends it")), "look off: Esc v is the plain line it was",
       since2()[-300:])
    sh.expect("heard -- Enter asks it")
    sh.send("\x15")
    sh.settle()
    if shell == "zsh":
        sh.read(6.0)                           # a blink's period: nothing may come
    seen = since()
    ok(not any(f in seen for f in EVERY_FACE) and seen.count("\x1b7") == seen.count("\x1b7\x1b[2A\r\x1b[2K* ") + 1,
       "look off: no face, and no frame but the lines spark says and the one Ctrl-U clears", seen[-400:])

    sh.send("exit 7\r")
    sh.read(1.0)
    sh.close()
    time.sleep(0.3)
    ok(not os.listdir(os.path.join(sd, "widgets")), "living: marker removed on exit")
    if shell == "bash":
        ok(lines(tlog) == ["it's the old trap 7"], "bash: the EXIT trap the rc set first still runs, and sees the exit status",
           lines(tlog))
    rendered_height(shell, widget, tmp, env, ok)
    failure_row(shell, widget, tmp, env, ok)
    no_blank_row(shell, widget, tmp, env, ok)
    idle_row(shell, widget, tmp, env, ok)
    if shell == "zsh":
        idle_motion(widget, tmp, env, ok)


def awake_state(tmp, name, height=1, colour="off"):
    """A state dir of its own holding an awake look file: the face on,
    the row `height` up."""
    state = os.path.join(tmp, name)
    os.makedirs(os.path.join(state, "spark"))
    with open(os.path.join(state, "spark", "look"), "w", encoding="utf-8") as f:
        f.write(LOOK_AWAKE.replace("HEIGHT=2", "HEIGHT=%d" % height).replace("COLOUR=on", "COLOUR=" + colour))
    return state


def no_blank_row(shell, widget, tmp, env, ok):
    """v1.80: the resting face is drawn only where the blank row is known.
    A prompt that opens with no newline has the last command's output in
    the row above; a prompt with more lines than the row is high has its
    own text there. Neither gets a face -- a line spark says still
    carries one."""
    env = dict(env, XDG_STATE_HOME=awake_state(tmp, "noblank-state"))
    env.pop("SPARK_HEIGHT", None)
    if shell == "bash":
        sh = Shell(["bash", "--norc", "--noprofile", "-i"], env, os.path.join(tmp, "work"))
        sh.send("PS1='NB> '; source %s; echo SOURCED\n" % widget)
    else:
        sh = Shell(["zsh", "-f", "-i"], env, os.path.join(tmp, "work"))
        sh.send("PROMPT='NB> '; source %s; echo SOURCED\n" % widget)
    try:
        sh.expect("SOURCED")
        sh.expect("NB> ")
        sh.settle()
        since = sh.mark()
        sh.send("\r")
        sh.expect("NB> ")
        sh.send("echo OUT-$((6*7))\r")
        sh.expect("OUT-42")
        sh.expect("NB> ")
        sh.settle()
        if shell == "zsh":
            sh.read(6.0)                       # a blink's period: no tick was armed
        seen = since()
        ok("(o.o)" not in seen and "(-.-)" not in seen and "\x1b7" not in seen,
           "no blank row: a prompt with no opening newline gets no resting face", seen[-300:])
        since = sh.mark()
        sh.send("sh -c 'exit 3'\r")
        ok(sh.expect("* (O.O) failed (3) -- Esc s asks why"), "no blank row: a failure line still carries its face",
           since()[-300:])
        sh.expect("NB> ")
        sh.settle()
        # two lines, the row one up: that row is the prompt's own text
        if shell == "bash":
            sh.send("PS1='\\nTOP-LINE\\nNB> '\r")
        else:
            sh.send("PROMPT=$'\\nTOP-LINE\\nNB> '\r")
        sh.expect("TOP-LINE")
        sh.expect("NB> ")
        sh.settle()
        since = sh.mark()
        sh.send("\r")
        sh.expect("TOP-LINE")
        sh.expect("NB> ")
        sh.settle()
        seen = since()
        ok("(o.o)" not in seen and "\x1b7" not in seen,
           "no blank row: a two-line prompt at height 1 gets no resting face", seen[-300:])
    finally:
        sh.send("\x15exit\r")
        sh.read(0.5)
        sh.close()


def idle_row(shell, widget, tmp, env, ok):
    """A real screen (v1.80): the resting face sits alone in the blank row
    above an idle prompt and is gone once Enter is pressed, so what
    scrolls up is what scrolled up before; output that ended without a
    newline keeps its last line."""
    if not shutil.which("tmux"):
        print("  skip idle row: no tmux")
        return
    env = dict(env, TERM="screen-256color", XDG_STATE_HOME=awake_state(tmp, "idle-state"))
    env.pop("SPARK_HEIGHT", None)
    t = ["tmux", "-S", os.path.join(tmp, "tmux-i.sock"), "-f", "/dev/null"]
    argv = "bash --norc --noprofile -i" if shell == "bash" else "zsh -f -i"
    cmd = "env -i HISTFILE=/dev/null " + " ".join(shlex.quote("%s=%s" % kv) for kv in env.items()) + " " + argv
    subprocess.run(t + ["new-session", "-d", "-x", "70", "-y", "16", "-c", os.path.join(tmp, "work"), cmd], check=True)

    def screen():
        rows = [r.rstrip() for r in subprocess.run(t + ["capture-pane", "-p"], capture_output=True, text=True).stdout.splitlines()]
        while rows and not rows[-1]:
            rows.pop()
        return rows

    def until(want, timeout=8):
        end = time.time() + timeout
        while time.time() < end:
            s = screen()
            if want(s):
                return s
            time.sleep(0.2)
        return screen()

    def keys(s):
        subprocess.run(t + ["send-keys", "-l", s], check=True)
        subprocess.run(t + ["send-keys", "Enter"], check=True)

    def show(good, rows):
        if not good:
            print("       screen:\n" + "\n".join("       |%s|" % r for r in rows))

    try:
        if shell == "bash":
            keys("PS1='\\nF> '; source %s; clear" % widget)
        else:
            keys("PROMPT=$'\\nF> '; source %s; clear" % widget)
        rows = until(lambda s: s == ["(o.o)", "F>"], 20)
        good = rows == ["(o.o)", "F>"]
        ok(good, "idle row: the resting face sits alone in the blank row above the prompt")
        show(good, rows)
        keys("echo OUT-LINE")
        want = ["", "F> echo OUT-LINE", "OUT-LINE", "(o.o)", "F>"]
        rows = until(lambda s: s == want)
        good = rows == want
        ok(good, "idle row: Enter erases the face; the next prompt has its own")
        show(good, rows)
        # output with no newline at its end: its last line stays, on screen
        # and after the next Enter
        keys("printf NO-EOL")
        rows = until(lambda s: s[-2:] == ["(o.o)", "F>"] and any(r.startswith("NO-EOL") for r in s))
        good = (rows[-2:] == ["(o.o)", "F>"] and len(rows) > 2 and rows[-3].startswith("NO-EOL")
                and rows.count("(o.o)") == 1)
        ok(good, "idle row: output with no final newline keeps its last line, the face in a row of its own")
        show(good, rows)
        keys("true")
        rows = until(lambda s: s[-3:] == ["F> true", "(o.o)", "F>"])
        good = (rows[-3:] == ["F> true", "(o.o)", "F>"] and rows.count("(o.o)") == 1
                and any(r.startswith("NO-EOL") for r in rows))
        ok(good, "idle row: scrollback keeps no face and loses no output")
        show(good, rows)
    finally:
        subprocess.run(t + ["kill-server"], stderr=subprocess.DEVNULL)


def idle_motion(widget, tmp, env, ok):
    """v1.80, zsh alone: with no key for a while the face sleeps, two
    frames in turn, and the next key wakes it -- the waking face at the
    key, the resting one a tick later. SPARK_IDLE_SLEEP is the widget's
    seam for the five minutes."""
    env = dict(env, XDG_STATE_HOME=awake_state(tmp, "motion-state"), SPARK_IDLE_SLEEP="3")
    env.pop("SPARK_HEIGHT", None)
    sh = Shell(["zsh", "-f", "-i"], env, os.path.join(tmp, "work"))
    try:
        since = sh.mark()
        sh.send("PROMPT=$'\\nMO> '; source %s; echo SOURCED\n" % widget)
        sh.expect("SOURCED")
        ok(sh.expect(ROW % (1, "(o.o)")), "zsh: the resting face at a one-line prompt, one row up", since()[-300:])
        since = sh.mark()
        ok(sh.expect(ROW % (1, "(-.-)z"), 8), "zsh: asleep after the delay with no key", since()[-300:])
        ok(sh.expect(ROW % (1, "(-.-)"), 5) and sh.expect(ROW % (1, "(-.-)z"), 5),
           "zsh: asleep, two frames in turn", since()[-300:])
        ok(ROW % (1, "(o.o)") not in since(), "zsh: asleep, no blink", since()[-300:])
        since = sh.mark()
        sh.send("e")
        ok(sh.expect(ROW % (1, "(-o-)"), 3), "zsh: the next key wakes the face", since()[-300:])
        ok(sh.expect(ROW % (1, "(o.o)"), 4), "zsh: awake again, the resting face a tick later", since()[-300:])
        sh.send("cho WOKE-$((6*7))\r")
        ok(sh.expect("WOKE-42") and (ROW % (1, "")) in since(),
           "zsh: the key that woke it is in the line, and Enter erases the face", since()[-300:])
        # Ctrl-L: the screen is new, and the tick stops until the next prompt
        sh.expect("MO> ")
        sh.settle()
        sh.send("\x0c")
        sh.settle()
        since = sh.mark()
        sh.read(6.0)
        ok("\x1b7" not in since(), "zsh: after Ctrl-L no tick draws until the next prompt", since()[-300:])
    finally:
        sh.send("exit\r")
        sh.read(0.5)
        sh.close()


ALERT_SEQ = 1791099000


def alert_line(n, mark, row, text, mood=None):
    """One line of the alert file as `spark check` writes it: seq, epoch,
    mark, mood, row, then the text."""
    return "%d %d %s %s %s %s\n" % (ALERT_SEQ + n, ALERT_SEQ + n, mark,
                                    mood or ("alarmed" if mark == "!" else "pleased"), row, text)


def alert_row(shell, widget, tmp, env, ok):
    """v1.81: a check row that turned worse is said at the next prompt,
    once in each pane, and once more when it heals -- only where the
    warning was shown. The alert file is a fixture written by hand here,
    whole and by a rename, as `spark check` writes it. A failure line
    goes first and the warning waits one prompt; `spark off` is silent
    and keeps it; a line that is not printable ASCII, or whose seq, mark
    or row is off, is dropped; two lines take two prompts, oldest first.
    The look file and the alert file share the shell's marker, and
    neither hides the other. Awake, the line carries the face its mark
    chooses, whatever mood the file names; not awake, no face. An
    answer to a paste is pleased."""
    state = os.path.join(tmp, "alert-state")
    sd = os.path.join(state, "spark")
    os.makedirs(sd)
    alert, look, off = (os.path.join(sd, n) for n in ("alert", "look", "off"))
    env = dict(env, XDG_STATE_HOME=state)
    env.pop("SPARK_HEIGHT", None)
    prompt = "AL> "

    def put(path, text):
        # a second later than the shell's marker, whatever the clock's
        # grain; whole and by a rename, 0600
        time.sleep(1.1)
        data = text if isinstance(text, bytes) else text.encode()
        with open(path + ".tmp", "wb") as f:
            f.write(data)
        os.chmod(path + ".tmp", 0o600)
        os.replace(path + ".tmp", path)

    def start(ps, extra=None):
        e = dict(env, **(extra or {}))
        if shell == "bash":
            sh = Shell(["bash", "--norc", "--noprofile", "-i"], e, os.path.join(tmp, "work"))
            sh.send("PS1='%s'; source %s; echo SOURCED\n" % (ps, widget))
        else:
            sh = Shell(["zsh", "-f", "-i"], e, os.path.join(tmp, "work"))
            sh.send("PROMPT=$'%s'; source %s; echo SOURCED\n" % (ps, widget))
        since = sh.mark()
        sh.expect("SOURCED\r\n")
        sh.expect(prompt)
        sh.settle()
        return sh, since()

    def enter(sh, keys=""):
        """Enter, the next prompt, and everything written until the
        terminal is quiet (zsh draws its row after the prompt)."""
        since = sh.mark()
        sh.send(keys + "\r")
        sh.expect(prompt)
        sh.settle()
        return since()

    def said(seen, text, height=1, top=""):
        """the note in spark's row: zsh's frame, `height` rows up; in bash
        the line the prompt's own opening newline ends"""
        if shell == "zsh":
            return (ROW % (height, text)) in seen
        return re.search(re.escape(text) + r"(\x1b\[\?2004h)?\r*\n" + re.escape(top or prompt), seen) is not None

    down = "serve: nothing answers on 127.0.0.1:8080 -- spark serve on"
    put(alert, alert_line(-10, "*", "forge", "forge: ok again, after 3 min") + alert_line(0, "!", "serve", down))
    sh, seen = start("\\n" + prompt)
    try:
        ok(said(seen, "! " + down) and seen.count(down) == 1,
           "alert: a new shell says the standing warning once, at its first prompt", seen[-300:])
        ok("forge: ok again" not in seen, "alert: a new shell says no heal", seen[-300:])
        ok(not any(f in seen for f in EVERY_FACE), "alert, not awake: the plain line, no face", seen[-300:])
        ok(os.stat(alert).st_mode & 0o777 == 0o600 and open(alert).read().count("\n") == 2,
           "alert: no pane writes the file")
        seen = enter(sh)
        ok(down not in seen, "alert: said once -- not at the prompt after", seen[-300:])
        put(alert, alert_line(-10, "*", "forge", "forge: ok again, after 3 min") + alert_line(0, "!", "serve", down))
        seen = enter(sh) + enter(sh)
        ok(down not in seen and "ok again" not in seen,
           "alert: the same line in a file written anew is not said again", seen[-300:])

        # the heal: only for a row whose warning this pane showed
        put(alert, alert_line(20, "*", "git", "git: ok again, after 2 min")
            + alert_line(21, "*", "serve", "serve: ok again, after 21 min"))
        seen = enter(sh)
        ok(said(seen, "* serve: ok again, after 21 min") and "git: ok again" not in seen,
           "alert: a heal is said where its warning was shown, and only that one", seen[-300:])
        seen = enter(sh) + enter(sh)
        ok("ok again" not in seen, "alert: the heal is said once", seen[-300:])

        # a failure line goes first; the warning waits one prompt
        put(alert, alert_line(30, "!", "git", "git: 2 files changed -- git status"))
        seen = enter(sh, "sh -c 'exit 3'")
        ok("failed (3) -- Esc s asks why" in seen and "git: 2 files changed" not in seen,
           "alert: a failed command says its own line first", seen[-300:])
        seen = enter(sh)
        ok(said(seen, "! git: 2 files changed -- git status"), "alert: the warning waited one prompt", seen[-300:])
        seen = enter(sh)
        ok("git: 2 files" not in seen, "alert: and is said once", seen[-300:])

        # spark off: silent, nothing marked seen; after spark on it shows
        open(off, "w").close()
        put(alert, alert_line(40, "!", "serve", "serve: down again -- spark serve on"))
        seen = enter(sh) + enter(sh)
        ok("down again" not in seen, "alert: spark off is silent", seen[-300:])
        os.remove(off)
        seen = enter(sh)
        ok(said(seen, "! serve: down again -- spark serve on"), "alert: after spark on the standing line shows",
           seen[-300:])
        seen = enter(sh)
        ok("down again" not in seen, "alert: once", seen[-300:])

        # what is not a clean line is dropped: an escape, a byte beyond
        # ASCII, a seq that is not 1 to 12 digits, another mark, a row
        # that is not a-z, a text past 200 characters. The eighth line
        # is clean, and the ninth is never read
        bad = (alert_line(50, "!", "aaa", "bad-escape \x1b[2J here").encode()
               + alert_line(51, "!", "bbb", "bad-latin caf").encode()[:-1] + b"\xc3\xa9\n"
               + b"17x1 17 ! alarmed ccc bad-seq-letters\n"
               + b"1234567890123 17 ! alarmed ddd bad-seq-long\n"
               + alert_line(52, "?", "eee", "bad-mark").encode()
               + alert_line(53, "!", "x9", "bad-row").encode()
               + alert_line(54, "!", "ggg", "bad-long-" + "x" * 192).encode()
               + alert_line(55, "!", "disk", "disk: 97 % full -- spark clear --history").encode()
               + alert_line(56, "!", "hhh", "bad-ninth-line").encode())
        put(alert, bad)
        seen = enter(sh)
        ok(said(seen, "! disk: 97 % full -- spark clear --history"), "alert: a clean line among bad ones is said",
           seen[-300:])
        seen += enter(sh) + enter(sh)
        ok("bad-" not in seen and "\x1b[2J" not in seen,
           "alert: an escape, a byte beyond ASCII, a bad seq, mark or row, a long text and a ninth line are dropped",
           seen[-400:])

        # two warnings take two prompts, oldest first; two rows of one
        # run (one seq) too
        put(alert, alert_line(60, "!", "aaa", "aaa: first of two -- one")
            + alert_line(61, "!", "bbb", "bbb: second of two -- two"))
        seen = enter(sh)
        ok(said(seen, "! aaa: first of two -- one") and "second of two" not in seen,
           "alert: two lines, one a prompt, the oldest first", seen[-300:])
        seen = enter(sh)
        ok(said(seen, "! bbb: second of two -- two") and "first of two" not in seen,
           "alert: the second line at the next prompt", seen[-300:])
        seen = enter(sh)
        ok("of two" not in seen, "alert: then neither", seen[-300:])
        put(alert, alert_line(70, "!", "ccc", "ccc: one run -- three") + alert_line(70, "!", "ddd", "ddd: one run -- four"))
        first, second, third = enter(sh), enter(sh), enter(sh)
        ok(said(first, "! ccc: one run -- three") and said(second, "! ddd: one run -- four")
           and "one run" not in third, "alert: two rows with one seq are each said once",
           (first + second + third)[-400:])

        # one marker, two files: the alert written first, the look after
        # it -- the look's read writes the marker anew, and the warning
        # is still said at that prompt, with the face the look brought
        put(alert, alert_line(80, "!", "eee", "eee: both at once -- x"))
        put(look, LOOK_AWAKE.replace("HEIGHT=2", "HEIGHT=1").replace("COLOUR=on", "COLOUR=off"))
        seen = enter(sh)
        ok(said(seen, "! (O.O) eee: both at once -- x"),
           "alert and look changed together: both are read, the warning carries the face", seen[-300:])
        # the alert's read wrote the marker: a look changed after it is
        # still read
        put(look, "AWAKE=no\nMOTION=off\nCOLOUR=off\nWORDS=off\nHEIGHT=1\n")
        seen = enter(sh, "sh -c 'exit 4'")
        ok("* failed (4) -- Esc s asks why" in seen and not any(f in seen for f in EVERY_FACE),
           "look changed after an alert was read: it is read again", seen[-300:])
        # both changed, and a failure took the prompt: the warning waits
        # past the marker the look's read wrote
        put(alert, alert_line(90, "!", "fff", "fff: waited for the failure -- y"))
        put(look, LOOK_AWAKE.replace("HEIGHT=2", "HEIGHT=1").replace("COLOUR=on", "COLOUR=off"))
        seen = enter(sh, "sh -c 'exit 5'")
        ok("* (O.O) failed (5) -- Esc s asks why" in seen and "waited for the failure" not in seen,
           "alert and look changed, a command failed: the failure line first, by the new look", seen[-300:])
        seen = enter(sh)
        ok(said(seen, "! (O.O) fff: waited for the failure -- y"),
           "alert: the warning that waited is said, though the marker is newer now", seen[-300:])
        seen = enter(sh)
        ok("waited for the failure" not in seen, "alert: and once", seen[-300:])
        ok(open(alert).read() == alert_line(90, "!", "fff", "fff: waited for the failure -- y"),
           "alert: the file is as it was written -- no pane writes it")
    finally:
        sh.send("\x15exit\r")
        sh.read(0.5)
        sh.close()

    # a new pane, awake, the row two up: the standing warning once, with
    # the alarmed face -- the widget's own, whatever mood the file names
    # -- and no heal; then the heal, pleased; then a paste's answer
    put(look, LOOK_AWAKE.replace("COLOUR=on", "COLOUR=off"))
    put(alert, alert_line(100, "*", "git", "git: ok again, after 2 min", mood="alarmed")
        + alert_line(101, "!", "serve", "serve: still down -- spark serve on", mood="pleased"))
    sh, seen = start("\\nINFO-LINE\\n" + prompt, {"SPARK_HEIGHT": "2"})
    try:
        ok(said(seen, "! (O.O) serve: still down -- spark serve on", 2, "INFO-LINE") and "ok again" not in seen,
           "alert, awake: the alarmed face after the mark, two rows up; a new pane says no heal", seen[-300:])
        ok("(o.o)" not in seen and "(^.^)" not in seen,
           "alert, awake: the note keeps the row -- no resting face over it, and no face the file named", seen[-300:])
        seen = enter(sh)
        ok("still down" not in seen and "(o.o)" in seen, "alert, awake: the next prompt has its resting face again",
           seen[-300:])
        put(alert, alert_line(102, "*", "serve", "serve: ok again, after 9 min", mood="alarmed"))
        seen = enter(sh)
        ok(said(seen, "* (^.^) serve: ok again, after 9 min", 2, "INFO-LINE"),
           "alert, awake: the heal carries the pleased face", seen[-300:])
        since = sh.mark()
        sh.send("\x1b[200~echo P-ONE\necho P-TWO\x1b[201~")
        ok(sh.expect(ROW % (2, "* (^.^) two echo lines, harmless -- pasted, not run")),
           "paste, awake: an answer carries the pleased face", since()[-300:])
        sh.settle()
    finally:
        sh.send("\x03")
        sh.settle()
        sh.send("exit\r")
        sh.read(0.5)
        sh.close()
    time.sleep(0.3)
    ok(not os.listdir(os.path.join(sd, "widgets")), "alert: markers removed on exit")


def interrupt_row(widget, tmp, env, ok):
    """v1.81, zsh alone: Ctrl-C at a prompt leaves no resting face in the
    scrollback, on a real screen. zsh fires no hook at a Ctrl-C, and a
    TRAPINT function would stop precmd from running after one: the
    widget defines none, and the next prompt's hook erases the face
    still standing. $? is 130 as it was, precmd runs as it did, a
    TRAPINT of the user's is theirs; a line accepted by a widget that
    is not spark's loses its face too."""
    env = dict(env, XDG_STATE_HOME=awake_state(tmp, "interrupt-state"))
    env.pop("SPARK_HEIGHT", None)
    sh = Shell(["zsh", "-f", "-i"], env, os.path.join(tmp, "work"))
    try:
        sh.send("TRAPINT() { print -n MINE-INT; return $(( 128 + $1 )) }; PROMPT=$'\\nIN> '; source %s; echo SOURCED\n"
                % widget)
        sh.expect("SOURCED\r\n")
        sh.expect("IN> ")
        sh.settle()
        since = sh.mark()
        sh.send("functions TRAPINT; echo TRAP-$((6*7))\r")
        sh.expect("TRAP-42\r\n")
        ok("MINE-INT" in since() and "_spark" not in since(), "zsh: a TRAPINT of the user's is left as it was",
           since()[-300:])
    finally:
        sh.send("exit\r")
        sh.read(0.5)
        sh.close()
    sh = Shell(["zsh", "-f", "-i"], env, os.path.join(tmp, "work"))
    try:
        sh.send("PROMPT=$'\\nIN> '; n=0; precmd() { (( ++n )) }; source %s; echo SOURCED\n" % widget)
        sh.expect("SOURCED\r\n")
        ok(sh.expect(ROW % (1, "(o.o)")), "zsh: the resting face above the prompt")
        sh.settle()
        since = sh.mark()
        sh.send("\x03")
        ok(sh.expect("\x1b7\x1b[2A\r\x1b[2K\x1b8") and sh.expect(ROW % (1, "(o.o)")),
           "zsh: after Ctrl-C the face left standing is erased, and the new prompt has its own", since()[-300:])
        sh.settle()
        since = sh.mark()
        sh.send("echo RC-$? TRAP-${+functions[TRAPINT]} N-$n\r")
        ok(sh.expect("RC-130 TRAP-0 N-2\r\n"),
           "zsh: after Ctrl-C $? is 130, precmd ran, and the widget defined no TRAPINT", since()[-300:])
        sh.expect("IN> ")
        sh.settle()
    finally:
        sh.send("exit\r")
        sh.read(0.5)
        sh.close()
    if not shutil.which("tmux"):
        print("  skip interrupt row: no tmux")
        return
    env = dict(env, TERM="screen-256color")
    t = ["tmux", "-S", os.path.join(tmp, "tmux-c.sock"), "-f", "/dev/null"]
    cmd = "env -i HISTFILE=/dev/null " + " ".join(shlex.quote("%s=%s" % kv) for kv in env.items()) + " zsh -f -i"
    subprocess.run(t + ["new-session", "-d", "-x", "70", "-y", "20", "-c", os.path.join(tmp, "work"), cmd], check=True)

    def screen():
        rows = [r.rstrip() for r in subprocess.run(t + ["capture-pane", "-p"], capture_output=True, text=True).stdout.splitlines()]
        while rows and not rows[-1]:
            rows.pop()
        return rows

    def until(want, timeout=8):
        end = time.time() + timeout
        while time.time() < end:
            s = screen()
            if s == want:
                return s
            time.sleep(0.2)
        return screen()

    def check(want, what):
        rows = until(want)
        ok(rows == want, what)
        if rows != want:
            print("       screen:\n" + "\n".join("       |%s|" % r for r in rows))

    def keys(*k, literal=""):
        if literal:
            subprocess.run(t + ["send-keys", "-l", literal], check=True)
        if k:
            subprocess.run(t + ["send-keys"] + list(k), check=True)

    try:
        keys("Enter", literal="PROMPT=$'\\nF> '; w() { zle .accept-line }; zle -N w; bindkey '^T' w; source %s; clear"
             % widget)
        check(["(o.o)", "F>"], "interrupt row: the resting face above the prompt")
        keys("C-c", literal="abc")
        check(["", "F> abc", "(o.o)", "F>"], "interrupt row: Ctrl-C on a typed line leaves no face above it")
        keys("C-c")
        check(["", "F> abc", "", "F>", "(o.o)", "F>"], "interrupt row: Ctrl-C at an empty prompt leaves no face")
        keys("Enter", literal="echo RC-$?-")
        check(["", "F> abc", "", "F>", "", "F> echo RC-$?-", "RC-130-", "(o.o)", "F>"],
              "interrupt row: $? is 130 after it, and the scrollback holds one face, the resting one")
        keys("C-t", literal="echo OTHER-ENTER")
        check(["", "F> abc", "", "F>", "", "F> echo RC-$?-", "RC-130-", "", "F> echo OTHER-ENTER", "OTHER-ENTER",
               "(o.o)", "F>"], "interrupt row: a line accepted by another widget loses its face too")
        # a command that is interrupted while it runs: Enter erased the
        # face already, and nothing is erased twice
        keys("Enter", literal="echo KEPT-LINE; sleep 30")
        until(None, 1)
        keys("C-c")
        rows = until(None, 1.5)
        good = (rows[-2:] == ["(o.o)", "F>"] and "KEPT-LINE" in rows and rows.count("(o.o)") == 1
                and any(r.startswith("F> echo KEPT-LINE; sleep 30") for r in rows))
        ok(good, "interrupt row: Ctrl-C in a running command erases no row of its output")
        if not good:
            print("       screen:\n" + "\n".join("       |%s|" % r for r in rows))
    finally:
        subprocess.run(t + ["kill-server"], stderr=subprocess.DEVNULL)


def failure_row(shell, widget, tmp, env, ok):
    """A real screen (v1.72): a failure says so in the hint row, the blank
    row above a plain prompt, and Esc s replaces it there -- one row,
    never one line above another."""
    if not shutil.which("tmux"):
        print("  skip failure row: no tmux")
        return
    # a state of its own: no look file, so the row is the one above
    env = dict(env, TERM="screen-256color", XDG_STATE_HOME=os.path.join(tmp, "failure-state"))
    env.pop("SPARK_HEIGHT", None)
    t = ["tmux", "-S", os.path.join(tmp, "tmux-f.sock"), "-f", "/dev/null"]
    argv = "bash --norc --noprofile -i" if shell == "bash" else "zsh -f -i"
    cmd = "env -i HISTFILE=/dev/null " + " ".join(shlex.quote("%s=%s" % kv) for kv in env.items()) + " " + argv
    subprocess.run(t + ["new-session", "-d", "-x", "70", "-y", "14", "-c", os.path.join(tmp, "work"), cmd], check=True)

    def screen():
        return [r.rstrip() for r in subprocess.run(t + ["capture-pane", "-p"], capture_output=True, text=True).stdout.splitlines()]

    def until(want, timeout=8):
        end = time.time() + timeout
        while time.time() < end:
            s = screen()
            if want(s):
                return s
            time.sleep(0.2)
        return screen()

    def keys(s, enter=True):
        subprocess.run(t + ["send-keys", "-l", s], check=True)
        if enter:
            subprocess.run(t + ["send-keys", "Enter"], check=True)

    try:
        if shell == "bash":
            keys("PS1='\\nF> '; source %s; clear" % widget)
        else:
            keys("PROMPT=$'\\nF> '; source %s; clear" % widget)
        until(lambda s: s[:2] == ["", "F>"], 20)
        time.sleep(0.5)
        keys("echo OUT-LINE; sh -c 'exit 3'")
        rows = until(lambda s: any("failed (3)" in r for r in s))
        at = next((i for i, r in enumerate(rows) if "failed (3)" in r), -1)
        good = (0 < at < len(rows) - 1 and rows[at] == "* failed (3) -- Esc s asks why"
                and rows[at - 1] == "OUT-LINE" and rows[at + 1] == "F>")
        ok(good, "failure row: the failure line is the hint row, right above the prompt")
        if not good:
            print("       screen:\n" + "\n".join("       |%s|" % r for r in rows))
        time.sleep(0.3)
        subprocess.run(t + ["send-keys", "Escape", "s"], check=True)
        rows = until(lambda s: any("Enter explains the error" in r for r in s))
        at = next((i for i, r in enumerate(rows) if "Enter explains the error" in r), -1)
        good = (0 < at < len(rows) - 1 and rows[at - 1] == "OUT-LINE" and rows[at + 1].startswith("F> { echo OUT-LINE")
                and not any("failed (3)" in r for r in rows))
        ok(good, "failure row: Esc s replaces the failure line in the same row")
        if not good:
            print("       screen:\n" + "\n".join("       |%s|" % r for r in rows))
    finally:
        subprocess.run(t + ["kill-server"], stderr=subprocess.DEVNULL)


def voice_keys(shell, widget, tmp, env, ok):
    """v1.70: Esc v and Esc x are bound only where the voice is on or
    clear when the shell starts -- SPARK_VOICE from the environment, else
    spark.env's line; off (or unset), the keys stay the shell's own
    (zsh's Esc x is execute-named-cmd)."""
    vhome = os.path.join(tmp, "vhome")
    conf = os.path.join(vhome, ".config", "spark")
    os.makedirs(conf, exist_ok=True)
    os.makedirs(os.path.join(vhome, ".local", "state"), exist_ok=True)
    base = {k: v for k, v in env.items() if k != "SPARK_VOICE"}
    base.update(HOME=vhome, XDG_STATE_HOME=os.path.join(vhome, ".local", "state"), ZDOTDIR=vhome)
    if shell == "bash":
        argv = ["bash", "--norc", "--noprofile", "-i"]
        ask = "bind -X | grep -cE '_spark_(listen|hush)' ; echo VOICE-KEYS-$((6*7))"
    else:
        argv, ask = ["zsh", "-f", "-i"], "bindkey '\\ex'; bindkey '\\ev'; echo VOICE-KEYS-$((6*7))"
    for label, voice_env, file_line, bound in (
            ("unset, no spark.env", None, None, False),
            ("unset, spark.env says clear", None, 'SPARK_VOICE="clear"', True),
            ("unset, spark.env says off", None, "SPARK_VOICE=off", False),
            ("the environment off over spark.env's clear", "off", "SPARK_VOICE=clear", False),
            ("the environment on", "on", None, True)):
        envf = os.path.join(conf, "spark.env")
        if os.path.exists(envf):
            os.remove(envf)
        if file_line:
            with open(envf, "w") as f:
                f.write("SPARK_PORT=8080\n" + file_line + "\n")
        e = dict(base, **({"SPARK_VOICE": voice_env} if voice_env else {}))
        sh = Shell(argv, e, os.path.join(tmp, "work"))
        try:
            sh.send("source %s; echo SOURCED\n" % widget)
            sh.expect("SOURCED")
            sh.settle()
            since = sh.mark()
            sh.send(ask + "\n")
            sh.expect("VOICE-KEYS-42", 5)
            sh.settle()
            out = since()
        finally:
            sh.send("exit\n")
            sh.read(0.5)
            sh.close()
        if shell == "bash":
            n = [l.strip() for l in out.splitlines() if l.strip().isdigit()]
            got = n[-1:] == ["2"] if bound else n[-1:] == ["0"]
        else:
            got = (("spark-hush" in out and "spark-listen" in out) if bound
                   else ("spark-hush" not in out and "spark-listen" not in out and "execute-named-cmd" in out))
        ok(got, "the voice keys, %s: Esc v and Esc x %s" % (label, "bound" if bound else "left to the shell"),
           out[-300:])


def moved_keys(shell, widget, tmp, env, ok):
    """`spark keys NAME KEY` writes ~/.config/spark/keys.env; the widget
    reads it as the shell starts. A moved key asks spark and the key it
    left does not; a key set to none is not bound; the hint names the key
    in use; and what each key did before is recorded once, in
    state/replaced.<shell>, not written again by the next shell. A value
    that holds shell syntax runs nothing and keeps the default key."""
    khome = os.path.join(tmp, "khome")
    conf = os.path.join(khome, ".config", "spark")
    state = os.path.join(khome, ".local", "state")
    os.makedirs(conf, exist_ok=True)
    os.makedirs(state, exist_ok=True)
    ran = [os.path.join(tmp, "keys-ran-%d" % i) for i in (1, 2, 3)]
    with open(os.path.join(conf, "keys.env"), "w") as f:
        f.write("# spark keys\nKEYS_ASK=Ctrl-g\nKEYS_RECALL=Alt-b\nKEYS_HEIGHT=none\nKEYS_STOP=Ctrl-c\n")
        # shell syntax in a value: the file is read, never sourced, so
        # nothing runs, and a value of that shape keeps the default
        f.write("KEYS_LISTEN=$(touch %s)\nKEYS_STOP=`touch %s`\nKEYS_LISTEN=Esc $(touch %s)\n" % tuple(ran))
    log, hlog = os.path.join(tmp, "keys-asked.log"), os.path.join(tmp, "keys-height.log")
    e = dict(env, HOME=khome, XDG_STATE_HOME=state, ZDOTDIR=khome, STUB_LOG=log, STUB_HEIGHT=hlog, STUB_RECALL=os.path.join(tmp, "keys-recall.log"))
    record = os.path.join(state, "spark", "replaced." + shell)

    def lines(path):
        try:
            with open(path) as f:
                return f.read().splitlines()
        except OSError:
            return []

    if shell == "bash":
        argv = ["bash", "--norc", "--noprofile", "-i"]
        bound = ("bind -X | grep -c _spark_height_key; bind -X | grep -cF '\\C-c'; "
                 "bind -X | grep -cF '\\ex'; echo KEYS-$((6*7))")
    else:
        argv, bound = ["zsh", "-f", "-i"], "bindkey '\\ek'; bindkey '\\ex'; bindkey '^C'; echo KEYS-$((6*7))"
    stamp = None
    for run in (1, 2):
        sh = Shell(argv, e, os.path.join(tmp, "work"))
        try:
            sh.send("%s; source %s; echo SOURCED\n" % ("PS1='\\nKP> '" if shell == "bash" else "PROMPT=$'\\nKP> '", widget))
            sh.expect("SOURCED")
            sh.settle()
            if run == 2:
                break
            since = sh.mark()
            sh.send("moved key words")
            time.sleep(0.3)
            sh.send("\x07")                              # Ctrl-g: ask, moved here
            got = sh.expect("A hint about it")
            ok(got and lines(log)[-1:] == ["moved key words"], "a moved key works: Ctrl-g asks about the line", since())
            sh.send("\x15")
            sh.settle()
            n = len(lines(log))
            sh.send("old key words")
            time.sleep(0.3)
            sh.send("\x1bs")                             # Esc s: the shell's own again
            sh.read(1.6)
            ok(len(lines(log)) == n, "the key it left does not call spark: Esc s asks nothing", lines(log)[n:])
            sh.send("\x03")
            sh.settle()
            since = sh.mark()
            sh.send("\x07")                              # on an empty line: the hint names the key
            ok(sh.expect("type a question, then Ctrl-g"), "the hint names the key in use (Ctrl-g, not Esc s)", since())
            since = sh.mark()
            sh.send("find the amend")
            time.sleep(0.3)
            sh.send("\x1bb")                             # Esc b (written Alt-b): recall, moved here
            ok(sh.expect("Esc b for the next"), "Alt-b in keys.env is Esc b: recall runs there and names it", since())
            sh.send("\x15")
            sh.settle()
            sh.send("\x1bk")                             # Esc k: set to none
            sh.read(1.6)
            sh.send("\x03")
            sh.settle()
            since = sh.mark()
            sh.send(bound + "\n")
            sh.expect("KEYS-42", 5)
            sh.settle()
            out = since()
            if shell == "bash":
                n = [l.strip() for l in out.splitlines() if l.strip().isdigit()]
                free = n[-3:] == ["0", "0", "1"]
            else:
                free = ('"^[k" undefined-key' in out and '"^[x" spark-hush' in out and '"^C" spark' not in out)
            ok(free and not lines(hlog), "a key set to none is not bound; a value spark cannot take (Ctrl-c) keeps "
               "the default key and binds no other", out[-300:])
            rec = lines(record)
            ok(any(l.startswith("ask\tCtrl-g\t") for l in rec) and any(l.startswith("recall\tEsc b\t") for l in rec)
               and not any(l.startswith("height\t") for l in rec),
               "what each key did before is recorded for spark keys (state/replaced.%s)" % shell, rec)
            ok(not any(os.path.exists(r) for r in ran) and any(l.startswith("listen\tEsc v\t") for l in rec)
               and any(l.startswith("stop\tEsc x\t") for l in rec),
               "shell syntax in a keys.env value ($(...), backticks) runs nothing, and the key keeps its default", rec)
            stamp = os.stat(record).st_mtime_ns if os.path.exists(record) else None
            time.sleep(1.1)
        finally:
            sh.send("exit\n")
            sh.read(0.5)
            sh.close()
    ok(stamp is not None and os.stat(record).st_mtime_ns == stamp,
       "the next shell finds the record as it is and does not write it again")


def keys_off(shell, widget, tmp, env, ok):
    """`spark keys off` writes KEYS=off in keys.env. The widget then
    binds none of its five keys, the voice's two included, and leaves
    the Esc wait as the shell has it. The rest works as with the keys
    on: a `? words` line asks spark on Enter, and a failed command is
    noted in the row -- with no key named. A per-key line in the same
    file stays unread while off."""
    khome = os.path.join(tmp, "offhome")
    conf = os.path.join(khome, ".config", "spark")
    state = os.path.join(khome, ".local", "state")
    os.makedirs(conf, exist_ok=True)
    os.makedirs(state, exist_ok=True)
    with open(os.path.join(conf, "keys.env"), "w") as f:
        f.write("KEYS_ASK=Ctrl-g\nKEYS=off\n")
    log = os.path.join(tmp, "off-asked.log")
    e = dict(env, HOME=khome, XDG_STATE_HOME=state, ZDOTDIR=khome, STUB_LOG=log, SPARK_VOICE="on")

    def lines(path):
        try:
            with open(path) as f:
                return f.read().splitlines()
        except OSError:
            return []

    if shell == "bash":
        argv = ["bash", "--norc", "--noprofile", "-i"]
        bound = ("bind -X | grep -cE '_spark_(ask_line|recall|height_key|listen|hush)'; "
                 "bind -v | grep keyseq-timeout; echo KEYS-$((6*7))")
    else:
        argv = ["zsh", "-f", "-i"]
        bound = ("bindkey '\\es'; bindkey '\\er'; bindkey '\\ek'; bindkey '\\ev'; bindkey '\\ex'; bindkey '^G'; "
                 "echo KT-$KEYTIMEOUT-; echo KEYS-$((6*7))")
    sh = Shell(argv, e, os.path.join(tmp, "work"))
    try:
        sh.send("%s; source %s; echo SOURCED\n" % ("PS1='\\nOP> '" if shell == "bash" else "PROMPT=$'\\nOP> '", widget))
        sh.expect("SOURCED")
        sh.settle()
        since = sh.mark()
        sh.send(bound + "\n")
        sh.expect("KEYS-42", 5)
        sh.settle()
        out = since()
        if shell == "bash":
            n = [l.strip() for l in out.splitlines() if l.strip().isdigit()]
            free = n[-1:] == ["0"] and "keyseq-timeout 1000" not in out
        else:
            free = ('"^[s" spell-word' in out and '"^[r" spark' not in out and '"^[k" spark' not in out
                    and '"^[v" spark' not in out and '"^[x" execute-named-cmd' in out and '"^G" spark' not in out
                    and "KT-40-" in out)
        ok(free, "KEYS=off: none of the five keys is spark's (a moved one neither), and the Esc wait is the shell's own",
           out[-400:])
        since = sh.mark()
        sh.send("? keys off words\r")
        got = sh.expect("A hint about it")
        ok(got and any("keys off words" in l for l in lines(log)),
           "KEYS=off: a ? words line still asks spark on Enter", since() + repr(lines(log)))
        sh.send("\x15")
        sh.settle()
        since = sh.mark()
        sh.send("sh -c 'exit 3'\r")
        got = sh.expect("failed (3)")
        sh.settle()
        out = since()
        ok(got and "? words asks about it" in out and "Esc s" not in out and "Ctrl-g" not in out,
           "KEYS=off: the failed note still shows, and names no key", out[-300:])
        rec = lines(os.path.join(state, "spark", "replaced." + shell))
        ok(not rec, "KEYS=off: no key is recorded as replaced", rec)
    finally:
        sh.send("exit\n")
        sh.read(0.5)
        sh.close()


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

        # 1. the first word: `spark awa<TAB>` becomes `spark awaken `
        since = sh.mark()
        sh.send("spark awa\t")
        ok(sh.expect("awaken"), "spark awa<TAB> completes to awaken", since())
        sh.send("\x15")     # C-u: clear the line
        time.sleep(0.2)

        # 2. a dynamic name, offline: `spark model gr<TAB>` -> granite-4-2-8b,
        #    read from models.env (the one model row that starts with gr)
        since = sh.mark()
        sh.send("spark model gr\t")
        # (a shell may redraw only the completed tail after the typed gr)
        ok(sh.expect("anite-4-2-8b"), "spark model gr<TAB> completes to granite-4-2-8b", since())
        sh.send("\x15")
        time.sleep(0.2)

        # 3. the one server verb's words (v1.64): `spark serve --lo<TAB>`
        #    -> --login, and `spark model --ch<TAB>` -> --chat
        since = sh.mark()
        sh.send("spark serve --lo\t")
        ok(sh.expect("gin"), "spark serve --lo<TAB> completes to --login", since())
        sh.send("\x15")
        time.sleep(0.2)
        since = sh.mark()
        sh.send("spark model --ch\t")
        ok(sh.expect("at"), "spark model --ch<TAB> completes to --chat", since())
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
        vlog = os.path.join(tmp, "voice.log")
        env = {"HOME": home, "XDG_STATE_HOME": state, "SPARK_BIN": stub, "STUB_LOG": log,
               "EXPLAIN_LOG": elog, "STUB_ENV": envlog, "STUB_VOICE": vlog, "STUB_HEARD": "list the big files",
               "SPARK_VOICE": "clear",
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
        if shell == "bash":
            # the reader keeps line 3's proof in a file: 0600 whatever the
            # shell's umask (this one runs under 022), gone at the next question
            pfs = []
            end = time.time() + 3
            while time.time() < end and not pfs:
                pfs = glob.glob(os.path.join(state, "spark", "proof.*"))
                time.sleep(0.05)
            modes = [oct(os.stat(p).st_mode & 0o777) for p in pfs]
            ok(len(pfs) == 1 and modes == ["0o600"], "streamed: the proof file is 0600 under umask 022", modes)
        sh.send("\x15")
        sh.settle()

        since = sh.mark()
        sh.send("? stream-danger\r")
        first, full = seen_then("DANGER-CMD", "! removes things -- read it before Enter")
        if shell == "bash":
            ok(not glob.glob(os.path.join(state, "spark", "proof.*")), "streamed: the next question removes the proof file")
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
        first, full = seen_then("ps aux -m", "Every process, the biggest memory first.", 15)
        ok("the ps manual has no --sort -- asking again" in first,
           "judged: the pulse row says why spark asks again", first[-400:])
        ok("--sort=" not in full and "ps aux -m" in full and "checked against" not in full,
           "judged: the wrong command never reaches the line; the re-ask's lands, its hint plain", full[-400:])
        sh.send("\x15")
        sh.settle()
        since = sh.mark()
        sh.send("? knowrisk show processes by memory\r")
        first, full = seen_then("rm -rf build", "Removes the build. -- read it before Enter", 15)
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
        ok(sh.expect("type a question, then Esc s"), "Esc s on an empty line explains itself")
        ok(asked() == n, "and does not ask")

        # 10. the failure moment: a nonzero exit prints one line, no model call
        n = asked()
        since = sh.mark()
        sh.send("sh -c 'exit 3'\r")
        ok(sh.expect("failed (3) -- Esc s asks why"), "a nonzero exit prints the failure line", since())
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
        ok(sh.expect("type a question, then Esc s"), "and Esc s stays the nag", since())
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
        ok(sh.expect("not found; Esc s gets the install line"), "127 prints the install note", since())
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
        got_p = sh.expect("test -d .") and sh.expect("runs the check")
        ok(got_p, "Esc s lands the read-only proof, ready to run", since())
        sh.send("\x15")
        sh.expect(prompt)

        # 7f. failure memory: a known shape's fix prints from the ONE
        # file the hook may read -- no model call, no fork
        with open(os.path.join(state, "spark", "fails"), "w") as f:
            f.write("abcdefabcdefabcd sh 3 echo mended\n")
        since = sh.mark()
        sh.send("sh -c 'exit 3'\r")
        ok(sh.expect("last time this fixed it: echo mended"),
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

        # 7i. the voice keys (v1.70): Esc v lands the heard words as a
        # question on an empty line and runs nothing; Enter asks spark
        n = asked()
        since = sh.mark()
        sh.send("\x1bv")
        ok(sh.expect("* listening -- a pause ends it"), "Esc v: the row says it listens", since())
        ok(sh.expect("heard -- Enter asks it") and sh.expect("? list the big files"),
           "Esc v: the heard words land in the line as a ? question", since())
        time.sleep(0.4)
        sh.read(0.4)
        try:
            with open(vlog) as f:
                vcalls = f.read().splitlines()
        except OSError:
            vcalls = []
        ok(asked() == n and "EXECUTED-MARK" not in since() and vcalls == ["voice listen --buffer"],
           "Esc v: nothing ran and nothing was asked -- only spark voice listen --buffer", (vcalls, since()[-200:]))
        sh.send("\r")
        ok(sh.expect("A hint about it"), "Esc v: Enter asks the heard question", since())
        with open(log) as f:
            last = f.read().splitlines()[-1:]
        ok(asked() == n + 1 and last == ["? list the big files"], "Esc v: spark line got the heard words", last)
        sh.send("\x15")
        sh.settle()
        # with words on the line: the heard ones join them at the cursor
        since = sh.mark()
        sh.send("echo hi")
        time.sleep(0.2)
        sh.send("\x1bv")
        ok(sh.expect("heard -- in your line"), "Esc v on a line: said where the words went", since())
        sh.send("\r")
        ok(sh.expect("hi list the big files"), "Esc v on a line: the words join at the cursor, run only on Enter",
           since())
        sh.expect(prompt)
        sh.settle()
        # nothing heard; a voice that cannot listen
        sh.send("export STUB_HEARD=\r")
        sh.expect(prompt)
        sh.settle()
        since = sh.mark()
        sh.send("\x1bv")
        ok(sh.expect("* nothing heard"), "Esc v, nothing heard: one quiet line", since())
        sh.send("export STUB_NOVOICE=1\r")
        sh.expect(prompt)
        sh.settle()
        since = sh.mark()
        sh.send("\x1bv")
        ok(sh.expect("Esc v needs the voice -- spark voice on"), "Esc v, no voice: says how to turn it on",
           since())
        sh.send("unset STUB_NOVOICE; export STUB_HEARD='list the big files'\r")
        sh.expect(prompt)
        sh.settle()
        # Esc x: spark voice stop
        sh.send("\x1bx")
        time.sleep(0.5)
        try:
            with open(vlog) as f:
                vcalls = f.read().splitlines()
        except OSError:
            vcalls = []
        ok(vcalls[-1:] == ["voice stop"], "Esc x: spark voice stop", vcalls)
        sh.settle()

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

        # 9b2. the alert (v1.81): a check row that turned worse, said once
        # in each pane; zsh's Ctrl-C leaves no face
        alert_row(shell, widget, tmp, env, ok)
        if shell == "zsh":
            interrupt_row(widget, tmp, env, ok)

        # 9c. the voice keys are bound only where the voice is on or clear
        voice_keys(shell, widget, tmp, env, ok)

        # 9d. the keys move (spark keys): keys.env read as the shell starts
        moved_keys(shell, widget, tmp, env, ok)

        # 9e. the keys off (spark keys off): none bound, the rest works
        keys_off(shell, widget, tmp, env, ok)

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
