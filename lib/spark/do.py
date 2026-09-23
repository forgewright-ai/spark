# spark.do -- a task done one confirmed command at a time (`spark do`).
#
# The model proposes ONE command per step (kind=cmd) with a hint, or says
# the goal is met (kind=done). Nothing runs until the user says so at the
# prompt: Enter runs it, e edits it first, s skips it, q quits; a step the
# model or persona.is_dangerous flags runs only on the literal `yes`. The
# output of each step (its last 4 kB) is the next user message, so the
# model reads what happened before proposing the next one; that message
# lands on the thread the moment the step ran (land), naming the command
# that actually ran, so the record is what happened and not what was
# proposed. The step's proof (contract 4) is offered the same way, runs
# on a leash, and only its exit code goes back: a proof's output never
# rides a request -- the proof is the model's own line, and forwarding
# what it printed would let the model choose what to read.
#
# propose() and run() take values and return values -- no terminal -- so
# the prompt and (later) the page share one code path. cmd_do is the
# terminal around them.
#
# Bounded and held: a proposal's messages fit the served context (fit,
# budget: the goal is never dropped, the oldest outputs go first), a
# step's output passes text.hold_secrets before it is fed back, and a
# step refused for an option it does not take brings back the lines of
# that command's own man page (man_excerpt) -- spark reads the page, the
# tool never runs for it. Every proposal is a turn record with the
# server's timings (Session.record), so do's cache hits are measured.
#
# Sandboxed (--sandbox, lib/spark/sandbox.py): every step runs in a copy of
# the project the kernel keeps it inside -- no network, nothing else
# writable, no new privileges, STEP_TIMEOUT a step -- so containment
# replaces the per-step Enter, and the person's Enter moves to the apply:
# the review (the diff), then the typed `yes`. A run nobody watches
# (--detach) waits for that review (--review, --accept, --discard).
# _drive is the one loop; a face (_Terminal) is who it asks and tells.

import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading

from . import MARK, config, die, glyph, page, paint, say
from . import bar, forge, persona, reveal, sandbox, session, wire
from . import text as textmod

DO_MAX_STEPS = 8
OUTPUT_TAIL = 4000          # what a step's output sends at most: its last 4 kB
PROOF_TIMEOUT = 30          # seconds a proof may run before it is killed (rc 124)
STEP_TIMEOUT = 120          # seconds a step no person watches may run (the page, a sandbox, a program): then rc 124
DO_MAX_TOKENS = 200         # a proposal's reply cap; the budget leaves it room
CTX_FALLBACK = 8192         # the served context when SPARK_CTX says nothing usable
# the share of the context the messages may fill: CHARS_PER_TOKEN is an
# average over prose, and a command's output (paths, hashes, columns)
# spends more tokens a character than that
CTX_SHARE = 0.8
TRIMMED = "(output trimmed, exit %s)"   # an old step's output, once the budget needs its room
# a feedback message as land() keeps it: the [cwd] line, then its first line
FEEDBACK_HEAD = re.compile(r"\A(?:\[cwd [^\n]*\]\n)?Output of `.*` \(exit (-?\d+)[;)]")
NO_OUTPUT = "(no output)"
SKIPPED = "The user skipped this step (%s). Do not propose it again: propose a different step, or reply done."
STDIN_HOOK = "SPARK_DO_STDIN"   # =1: confirmations come from stdin lines (tests)
# said once on stderr when the hook is on, before any step is offered: a
# transcript must show the confirmations were a harness's, not a person's
STDIN_BANNER = "spark do: confirmations come from stdin (SPARK_DO_STDIN) -- a harness, not a person"
# the goal of a sandboxed run says where it runs (the system prompt stays
# byte-identical to plain do's: the served prefix is shared)
SANDBOX_NOTE = "[sandbox: no network; only this directory is writable; changes are reviewed at the end]"
OVER_CAP = "the run wrote more than %d MB -- stopped; review what it did"
DETACH_LOCK = "detach.lock"   # in STATE/runs: one detached run at a time (an flock)
OPTIONS = ("-h", "--help", "--sandbox", "--detach", "--review", "--accept", "--discard")
# a coreutils checksum line -- md5sum, sha1sum, sha256sum, sha512sum:
# `DIGEST  NAME`, or `DIGEST *NAME` in binary mode -- keeps its digest:
# a hash a step was asked to print is not a secret, and 64 hex digits
# read as "a long base64 run". do's one exemption from the hold, a line
# of that exact shape only; anything else on the output is still held
CHECKSUM_LINE = re.compile(r"^([0-9a-f]{32,128})((?: \*|  )\S)", re.M)
# a control character in the model's command or proof: a terminal escape
# can draw a benign fake over what Enter would run, so the reply is
# refused whole -- it becomes a `done` with this hint
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
REFUSED_CONTROL = "the model's command carried control characters -- refused"

# The OS documents its tools: a step refused for an option brings back
# the lines of that command's own man page (man_excerpt). What a tool
# prints when it does not take an option -- GNU getopt ("unrecognized
# option '--x'", "invalid option -- 'x'"), BSD ("illegal option -- x"),
# git and Go ("unknown option", "unknown flag"), argparse
# ("unrecognized arguments"):
BAD_OPTION = re.compile(r"(?:unrecognized|invalid|unknown) (?:option|flag|argument)|illegal option", re.I)
MAN_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")   # a plain command name: no path, no option
MAN_MAX = 1500              # bytes of the page that go back at most
MAN_TIMEOUT = 5             # seconds man may take; then nothing is added
MAN_WIDTH = 80              # the page's columns (MANWIDTH)
MAN_BEFORE = 2              # lines kept above the one that names the flag
MAN_ENV_DROP = ("MANPAGER", "PAGER", "MANOPT")   # no pager or option of the user's own runs
MAN_HEADER = "From man %s:"
# the refused flag in the error line: getopt's `option -- x` first, then
# a flag as typed (-x, --long), then a quoted bare word (git's `frob')
SHORT_FLAG = re.compile(r"option -- ['`‘]?([A-Za-z0-9])")
TYPED_FLAG = re.compile(r"(?<![\w-])(--?[A-Za-z0-9][\w-]*)")
QUOTED_WORD = re.compile(r"option ['`\"‘]([A-Za-z0-9][\w-]*)")

DO_SCHEMA = dict(persona.LINE_SCHEMA, properties=dict(
    persona.LINE_SCHEMA["properties"], kind={"type": "string", "enum": ["cmd", "done"]}))

DO_USAGE = """%s do -- a task, step by step

  spark do <words>             the goal; one command at a time, you confirm each
  spark do --sandbox <words>   every step runs in a copy of this directory --
                               no network, nothing else writable -- without
                               asking; the changes once at the end: the diff,
                               then type yes to apply them
  spark do --sandbox --detach <words>
                               the same with nobody there (a timer, cron):
                               prints the run's id; its changes wait
  spark do --review [ID]       the runs waiting; with an ID its diff, then yes
  spark do --accept ID         apply a waiting run without asking (a script)
  spark do --discard ID        drop a waiting run
  spark do -- <words>          a goal that starts with - or is the word help

  Every step:  Enter runs it, e edits it first, s skips it, q quits.
  A step that can destroy data (sudo too) runs only when you type yes.
  After a step, its proof -- one read-only check -- is offered the same
  way; only its exit code goes back to the model, never its output.
  Sandboxed, steps (%d s at most each) and their proofs run on their own.
  At most %d steps per run; the output of each (last 4 kB) goes back
  to the model, a span that looks like a secret held back; a step
  refused for an option brings back those lines of its own man page.
  Every step is recorded as it ran (spark last, history).
"""


def shown(reply):
    """The step as the thread keeps it: `command` -- hint, or done -- hint."""
    if reply["kind"] == "done":
        return "done -- " + reply["hint"]
    return "`%s` -- %s" % (reply["command"], reply["hint"])


NUM_TOKEN = re.compile(r"\d[\d,.]*\d|\d")


def unchecked(hint, seen):
    """The done hint's number tokens that appear in none of the `seen`
    strings -- the goal, each feedback, each output tail. Commas are
    dropped on both sides and each seen string is searched as written
    and with its commas dropped. Substring on digits, on purpose:
    provenance, not arithmetic -- a claim needs a source, the way an
    action needs a confirmation."""
    texts = [(s, s.replace(",", "")) for s in seen if s]
    out = []
    for tok in NUM_TOKEN.findall(hint or ""):
        n = tok.strip(".,").replace(",", "")
        if not n or n in out:
            continue
        if any(n in a or n in b for a, b in texts):
            continue
        # "21,21,5" is an enumeration, not one number: it is proven when
        # every part is, and only the missing parts are named
        parts = [q for q in tok.strip(".,").split(",") if q]
        if len(parts) > 1:
            for q in parts:
                if q not in out and not any(q in a or q in b for a, b in texts):
                    out.append(q)
            continue
        out.append(n)
    return out


def conclusion_check(thread, reply, history=None):
    """unchecked() for a proposed reply: [] unless it is a done whose
    hint carries numbers no user message of the run backs. `seen` is
    every user-role text of the thread (the goal, each `Output of ...`
    feedback, each skip); `history` mirrors propose's -- the in-memory
    run when there is no thread on disk."""
    if reply.get("kind") != "done":
        return []
    if history is None:
        msgs = [m["text"] for m in forge.load(thread) if m.get("role") == "user"]
    else:
        msgs = [m["content"] for m in history if m.get("role") == "user"]
    return unchecked(reply.get("hint", ""), msgs)


def _driver(cfg, url, model, is_forge):
    """The stem of the model that drives the run: the ember role's when
    two models serve at the resolved url, else the brain's own stem.
    Nothing is hardcoded; the answer is whatever the server reports."""
    try:
        rows = wire.models(cfg, url, forge=is_forge)
    except wire.BrainError:
        rows = []
    if len(rows) > 1:
        for alias, stem, _loaded in rows:
            if alias == "ember":
                return stem
    return model


def budget(cfg, system_chars):
    """The characters a proposal's messages may fill: the served context
    (SPARK_CTX, the ember's; CTX_FALLBACK when unset or not a number)
    less the reply's DO_MAX_TOKENS, at the tree's own estimate of
    characters a token (reveal.CHARS_PER_TOKEN), a CTX_SHARE of that,
    less the system message."""
    try:
        ctx = int(cfg.ctx)
    except (TypeError, ValueError):
        ctx = CTX_FALLBACK
    if ctx <= 0:
        ctx = CTX_FALLBACK
    return max(0, int((ctx - DO_MAX_TOKENS) * reveal.CHARS_PER_TOKEN * CTX_SHARE) - system_chars)


def _trimmed(msg):
    """A step's feedback as one line, TRIMMED with its exit code; None
    for any other message (the goal, a skip, an assistant step)."""
    m = FEEDBACK_HEAD.match(msg["content"]) if msg.get("role") == "user" else None
    return TRIMMED % m.group(1) if m else None


def fit(msgs, room):
    """`msgs` -- a run as chat messages, [0] the goal, [-1] the newest --
    cut to `room` characters, as a new list: the oldest step outputs are
    shortened to TRIMMED first, then the oldest exchanges after the goal
    are dropped, an assistant step with the answer it got, so the roles
    still alternate. The goal and the newest step with its answer are
    always kept: a run that lost its goal proposes for nothing. The
    thread on disk keeps everything; only the request is cut."""
    out = [dict(m) for m in msgs]
    total = sum(len(m["content"]) for m in out)
    for m in out[1:-1]:
        if total <= room:
            break
        short = _trimmed(m)
        if short is not None and len(short) < len(m["content"]):
            total -= len(m["content"]) - len(short)
            m["content"] = short
    while total > room and len(out) > 3:
        total -= len(out.pop(1)["content"]) + len(out.pop(1)["content"])
    return out


def propose(cfg, thread, text, shell, cwd, history=None, brain=None, landed=False):
    """One step, no terminal: (reply, ms, session). reply is {"kind": cmd|done,
    "command", "hint", "danger", "proof"} with danger normalised (the
    model's flag or persona.is_dangerous), the proof kept only when
    persona.proof_ok takes it, and the hint scrubbed of escapes (it is
    printed into a live terminal). A command or proof carrying a control
    character is refused whole: the reply is a `done` whose hint is
    REFUSED_CONTROL. `history` is the run so far as chat messages,
    extended in place; None reads the thread from disk. `landed` says
    `text` is already the newest user message of both (land() put it
    there the moment the step ran), so the request rides the history up
    to it and only the reply is appended; otherwise both messages land
    here. `brain` goes to the Session (the FORGE's own upstream). The
    request is cut to the context (fit, budget); `history` itself is
    not. The Session comes back so the caller records the turn with the
    server's timings and the stem that answered (Session.record). Never
    runs anything. Raises BrainError."""
    s = session.Session(cfg, "do", shell, cwd, None, brain)
    room = budget(cfg, len(s._system()))
    if history is None:
        history = forge.history(thread, mode="do", room=room)
    sent = history if landed else history + [{"role": "user", "content": persona.user_message(text, cwd)}]
    s.history = fit(sent, room)[:-1]        # the newest message is `text`'s own, rebuilt by ask_json
    raw, ms = s.ask_json(text, DO_SCHEMA, max_tokens=DO_MAX_TOKENS)
    command = " ".join(str(raw.get("command") or "").split())
    hint = " ".join(textmod.scrub(str(raw.get("hint") or "")).split())
    proof = " ".join(str(raw.get("proof") or "").split())
    kind = "cmd" if raw.get("kind") == "cmd" and command else "done"
    if kind == "cmd" and (CONTROL.search(command) or CONTROL.search(proof)):
        kind, command, hint = "done", "", REFUSED_CONTROL
    reply = {"kind": kind, "command": command if kind == "cmd" else "", "hint": hint,
             "danger": kind == "cmd" and (bool(raw.get("danger")) or persona.is_dangerous(command)),
             "proof": proof if kind == "cmd" and persona.proof_ok(proof) else ""}
    if not landed:
        land(cfg, thread, history, text, cwd)
    history.append({"role": "assistant", "content": shown(reply)})
    forge.append(cfg, thread, "assistant", shown(reply), kind="danger" if reply["danger"] else kind)
    return reply, ms, s


def land(cfg, thread, history, text, cwd):
    """One user message onto the run, now: `history` in place (with the
    [cwd] line the wire carries) and the thread on disk. cmd_do lands a
    step's feedback here the moment the step ran, before any next
    propose, so the record holds what ran even when the run stops there;
    the next propose(landed=True) rides it without appending it again."""
    history.append({"role": "user", "content": persona.user_message(text, cwd)})
    forge.append(cfg, thread, "user", text, mode="do", cwd=cwd)


def run(command, shell, cwd="", echo=True, timeout=None, argv=None, env=None, preexec_fn=None):
    """Run one step through `shell -c`, its output echoed live to stdout
    (echo=False keeps quiet), stderr folded in. (rc, the last 4 kB).
    `timeout` (seconds) is a leash: the command runs in its own process
    group and the whole group is killed when it expires -- rc 124 with
    the tail so far. The proof runs on one, and so does a step no person
    watches (STEP_TIMEOUT: the page, a sandbox, a program); a step at the
    terminal does not -- the person there has Ctrl-C. A sandboxed step
    passes sandbox.step's `argv`, `cwd` and `env` and sandbox.preexec as
    `preexec_fn`. A run stopped mid-step (Ctrl-C, SIGTERM) takes a leashed
    step's group down with it: its own session is no terminal's to kill."""
    try:
        p = subprocess.Popen(argv or [shell, "-c", command], cwd=cwd or None, env=env, preexec_fn=preexec_fn,
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             start_new_session=timeout is not None)
    except OSError as e:
        return 127, "%s: %s" % ((argv or [shell])[0], e.strerror or e)
    expired = []

    def _expire():
        if p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGKILL)
                expired.append(True)
            except OSError:
                pass
    timer = threading.Timer(timeout, _expire) if timeout else None
    if timer is not None:
        timer.daemon = True
        timer.start()
    tail = ""
    try:
        with p.stdout:
            for raw in p.stdout:
                line = raw.decode("utf-8", errors="replace")
                if echo:
                    sys.stdout.write(line)
                    sys.stdout.flush()
                tail = (tail + line)[-OUTPUT_TAIL:]
        rc = p.wait()
    except BaseException:
        if timeout is not None and p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass
        raise
    finally:
        if timer is not None:
            timer.cancel()
    return (124 if expired else rc), tail


def hold(tail):
    """(held tail, spans held, their shapes' names): what a step printed,
    every span that looks like a secret (text.SOURCE_SHAPES) replaced by
    [held] -- the digest of a CHECKSUM_LINE excepted, read as blanks."""
    shown = CHECKSUM_LINE.sub(lambda m: "-" * len(m.group(1)) + m.group(2), tail)
    spans, names = textmod.held_spans(shown)
    return (textmod.hold_spans(tail, spans) if spans else tail), len(spans), names


def feedback(command, rc, tail, proposed="", proof="", prc=None, man=""):
    """The record of a step as it ran, and the next user message: the
    command that ran (`edited from` the proposal when the user changed
    it), what it printed, how it ended, `man` (man_excerpt's block) when
    there is one, and the proof's exit code alone when one ran -- never
    the proof's output. What it printed passes hold() first: a key or a
    token a step printed is the machine's, not the model's.
    (message, held, names): the spans held back, and their shapes."""
    tail, held, names = hold(tail)
    edited = ("; edited from `%s`" % proposed) if proposed and proposed != command else ""
    s = "Output of `%s` (exit %d%s):\n%s" % (command, rc, edited, tail.rstrip("\n") or NO_OUTPUT)
    if man:
        s += "\n\n" + man
    if proof and prc is not None:
        s += "\n\nProof `%s` exited %d." % (proof, prc)
    return s, held, names


def _refused_flag(line):
    """The flag an error line says was refused, as the page would list
    it (-x, --long), or ''."""
    m = SHORT_FLAG.search(line)
    if m:
        return "-" + m.group(1)
    m = TYPED_FLAG.search(line)
    if m:
        return m.group(1)
    m = QUOTED_WORD.search(line)
    if m:
        return ("--" if len(m.group(1)) > 1 else "-") + m.group(1)
    return ""


def _man_page(head):
    """`man -P cat HEAD` as argv, stdout only, overstrikes and escapes
    dropped; '' when man is missing, fails, or outlives MAN_TIMEOUT (its
    whole process group is killed: groff must not linger)."""
    env = dict(os.environ)
    for k in MAN_ENV_DROP:
        env.pop(k, None)
    env["MANWIDTH"] = str(MAN_WIDTH)
    try:
        p = subprocess.Popen(["man", "-P", "cat", head], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, env=env, start_new_session=True)
    except OSError:
        return ""
    try:
        out, _err = p.communicate(timeout=MAN_TIMEOUT)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
        p.communicate()
        return ""
    if p.returncode != 0:
        return ""
    return textmod.scrub(re.sub(".\x08", "", out.decode("utf-8", errors="replace")))


def man_excerpt(command, rc, tail):
    """`From man HEAD:` and the lines of HEAD's own man page about the
    option a step was refused for, or ''. Only when the step exited
    non-zero and its output says an option was refused (BAD_OPTION);
    HEAD is the command's first word (shlex), a plain name (MAN_NAME)
    that `which` finds. spark reads the page (_man_page); the tool
    itself never runs for it. Around the refused flag where the page
    names it (its own entry first, MAN_BEFORE lines above), else from
    the SYNOPSIS, else the page's first lines: MAN_MAX bytes at most,
    whole lines, one blank line in a row."""
    if rc == 0:
        return ""
    line = next((l for l in tail.splitlines() if BAD_OPTION.search(l)), "")
    if not line:
        return ""
    try:
        words = shlex.split(command)
    except ValueError:
        return ""
    head = words[0] if words else ""
    if not MAN_NAME.match(head) or not shutil.which(head):
        return ""
    page = _man_page(head)
    if not page.strip():
        return ""
    lines = [l.rstrip() for l in page.splitlines()]
    start, flag = -1, _refused_flag(line)
    if flag:
        tok = re.compile(r"(?<![\w-])%s(?![\w-])" % re.escape(flag))
        hits = [i for i, l in enumerate(lines) if tok.search(l)]
        at = next((i for i in hits if lines[i].lstrip().startswith("-")), hits[0] if hits else -1)
        if at >= 0:
            start = max(0, at - MAN_BEFORE)
    if start < 0:
        start = next((i for i, l in enumerate(lines) if l.strip() == "SYNOPSIS"), 0)
    out, size = [], 0
    for l in lines[start:]:
        if not l.strip() and (not out or not out[-1].strip()):
            continue
        size += len(l.encode("utf-8")) + 1
        if size > MAN_MAX:
            break
        out.append(l)
    body = "\n".join(out).rstrip()
    return (MAN_HEADER % head + "\n" + body) if body else ""


# ------------------------------------------------------------------ prompt
def _edit(command):
    """The command back from the user, pre-filled where readline can."""
    try:
        import readline
    except ImportError:
        readline = None
    if readline is not None:
        readline.set_startup_hook(lambda: readline.insert_text(command))
    else:
        say("  " + command)
    try:
        new = input("  > ")
    finally:
        if readline is not None:
            readline.set_startup_hook()
    return " ".join(new.split()) or command


def _mark():
    """the answer mark, in the accent at a tty (plain piped or unset)"""
    return paint(glyph("hammer"), "accent", sys.stdout)


def _short(path):
    """path with the home directory as ~ (its real path too: a sandboxed
    run's cwd is real)."""
    for home in (os.path.expanduser("~"), os.path.realpath(os.path.expanduser("~"))):
        if path.startswith(home + "/"):
            return "~" + path[len(home):]
    return path


def _plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


# ------------------------------------------------------------------ faces
class _Terminal:
    """A person at the terminal -- or SPARK_DO_STDIN's harness, or nobody
    at all (detach: a timer's log). The lines spark do has always
    printed, the prompts it has always asked; sandboxed, no prompt until
    the review, and a detached run leaves its changes waiting."""
    echo = True

    def __init__(self, detach=False):
        self.detach = detach

    def refuse(self, text):
        say("%s do -- %s" % (MARK, text))
        return 2

    def begin(self, driver, box, cwd, thread):
        say("%s driving with %s (a silence is the model thinking)" % (_mark(), driver))
        if box is not None:
            say("%s sandbox %s: a copy of %s, no network -- nothing there changes until you apply it"
                % (_mark(), box["id"], _short(cwd)))

    def think(self, fn):
        with textmod.Busy(sys.stderr):        # the pulse while the model proposes
            return fn()

    def brain(self, hint):
        print("spark: " + hint, file=sys.stderr, flush=True)

    def done(self, hint, bad):
        say("%s done  %s" % (glyph("warn" if bad else "ok"), hint))
        if bad:
            say("  unchecked: no command produced %s -- believe the outputs above" % ", ".join(bad))

    def warn(self, text):
        say("%s %s" % (glyph("warn"), text))

    def note(self, text):
        say("%s %s" % (_mark(), text))

    def missing(self, n, command, hint, word):
        from .cli import _one_line
        say("%s %d  %s   %s" % (glyph("warn"), n, command, _one_line("%s: not on this machine -- %s" % (word, hint))))

    def step(self, n, reply, contained):
        if reply["danger"]:
            say(paint("%s %d  %s   %s" % (glyph("warn"), n, reply["command"], reply["hint"]), "warn", sys.stdout))
            if contained:
                say("  %s can destroy data -- it runs in the sandbox's copy" % glyph("warn"))
        else:
            say("%s %d  %s   %s" % (_mark(), n, reply["command"], reply["hint"]))

    def confirm(self, reply, cwd):
        """(run|skip|quit, the command): Enter, e, s, q -- danger needs `yes`."""
        command = reply["command"]
        choice = _confirm(reply, cwd)
        if choice == "edit":
            command = _edit(command)
            reply["danger"] = bool(reply["danger"]) or persona.is_dangerous(command)
            choice = "run"
            if reply["danger"] and _confirm(reply, cwd) != "run":
                choice = "skip"
        return choice, command

    def ran(self, rc, shown):
        pass                                  # the output was echoed as it came

    def man(self, man):
        # what leaves is said: the page's lines ride the next request
        say("%s    %s %d lines go back with the output" % (_mark(), man.splitlines()[0], len(man.splitlines()) - 1))

    def proof(self, proof, cwd, contained, n):
        """(run|skip|quit, the proof) -- offered like a step; sandboxed it runs."""
        say("%s    proof: %s" % (_mark(), proof))
        if contained:
            return "run", proof
        try:
            choice = _confirm({"danger": False, "command": proof}, cwd)
            if choice == "edit":
                proof = _edit(proof)
                choice = "run"
                if not persona.proof_ok(proof):
                    say("  %s not a read-only proof -- skipped" % glyph("warn"))
                    choice = "skip"
        except EOFError:
            choice = "quit"        # nobody there; the step still lands
        return choice, proof

    def proof_ran(self, prc, shown):
        say("%s    proof -> %s" % (_mark(), "ok" if prc == 0 else "exit %d" % prc))

    def cap(self):
        say("%s step limit (%d) reached -- spark do again to continue" % (glyph("warn"), DO_MAX_STEPS))

    def eof(self):
        say()

    def stopped(self, steps):
        say("%s stopped after %s" % (_mark(), _plural(steps, "step")))

    def review(self, box, entries, n):
        """yes | keep: the diff, then the typed yes (grammar rule 5's second
        shape); a detached run keeps its changes for later."""
        if self.detach:
            return "keep"
        page(sandbox.diff_text(entries).rstrip("\n"))
        try:
            answer = input("apply %s to %s? type yes: " % (_plural(n, "change"), _short(box["cwd"]))).strip()
        except EOFError:
            say()
            answer = ""
        return "yes" if answer == "yes" else "keep"

    def nothing(self, box):
        say("%s nothing changed in the copy -- nothing to apply" % _mark())

    def applied(self, box, n, problems):
        say("%s applied %s to %s" % (_mark(), _plural(n, "change"), _short(box["cwd"])))
        for p in problems:
            say("  %s %s" % (glyph("warn"), p))

    def unapplied(self, box, text, paths):
        print("%s do -- %s" % (MARK, text), file=sys.stderr)
        for p in paths:
            print("  " + p, file=sys.stderr)
        print("  the run waits: spark do --review %s" % box["id"], file=sys.stderr, flush=True)

    def discarded(self, box):
        say("%s run %s discarded; nothing was applied" % (_mark(), box["id"]))

    def waits(self, box, n):
        say("%s run %s waits: %s -- spark do --review %s" % (_mark(), box["id"], _plural(n, "change"), box["id"]))

    def end(self, reason, hint, rc):
        pass


def _confirm(reply, cwd=""):
    """What the user wants for this step: run | edit | skip | quit."""
    if reply["danger"]:
        facts = persona.blast(reply.get("command", ""), cwd)
        if facts:
            say("  %s %s" % (glyph("arrow"), facts))
        answer = input("  this can destroy data -- type yes to run it: ").strip()
        return "run" if answer == "yes" else "skip"
    answer = input("  Enter runs it, e edits, s skips, q quits: ").strip().lower()
    return {"": "run", "e": "edit", "s": "skip", "q": "quit"}.get(answer, "skip")


# ------------------------------------------------------------------ the loop
def _shell_path(shell):
    return shutil.which(shell) or "/bin/sh"


def _step(face, command, shell, cwd, box, timeout):
    """(rc, tail) of one step: as typed here, or contained in the sandbox."""
    if box is None:
        return run(command, shell, cwd, echo=face.echo, timeout=timeout)
    argv, scwd, env = sandbox.step(box, _shell_path(shell), command)
    return run(command, shell, scwd, echo=face.echo, timeout=timeout, argv=argv, env=env,
               preexec_fn=sandbox.preexec)


def _drive(face, cfg, thread, goal, text, shell, cwd, box=None, timeout=None):
    """One run, whoever drives it: (rc, reason, hint) -- reason is done,
    cap, quit, refused or error. `text` is the goal as sent (a sandboxed
    run's carries SANDBOX_NOTE); `cwd` is where the steps run as the model
    reads it (a sandboxed run on macOS: the clone). Sandboxed (`box`),
    steps and proofs run without asking, on `timeout` each, and the run
    stops once the copy holds more than sandbox.SANDBOX_MAX_BYTES."""
    history, steps, seen, landed = [], 0, [], False
    skipped, reasked = set(), set()          # steps the user skipped; those re-asked once

    def record(s, **fields):
        """Every proposal is a turn: the server's timings for it (the
        prompt cache's hits among them) and the stem that answered."""
        s.record(thread=thread, line=goal, **fields)

    try:
        for n in range(1, DO_MAX_STEPS + 1):
            if box is not None and steps and sandbox.over_cap(box):
                msg = OVER_CAP % (sandbox.SANDBOX_MAX_BYTES >> 20)
                face.warn(msg)
                return 1, "cap", msg
            seen.append(text)
            try:
                reply, ms, s = face.think(lambda: propose(cfg, thread, text, shell, cwd, history, landed=landed))
            except wire.BrainError as e:
                bar.prompt_state(cfg, ai="down")
                face.brain(e.hint)
                return 1, "error", e.hint
            landed = False
            if reply["kind"] == "done":
                bad = unchecked(reply["hint"], seen)
                face.done(reply["hint"], bad)
                record(s, kind="done", answer=reply["hint"], ms=ms)
                return 0, "done", reply["hint"]
            proposed, command, hint = reply["command"], reply["command"], reply["hint"]
            if command.strip() in skipped:
                # the repair guard of a run: a step the user skipped comes
                # back verbatim -- once it is re-asked, twice it is the end
                if command.strip() in reasked:
                    msg = "the same step again after a skip -- stopped (say the goal another way)"
                    face.warn(msg)
                    record(s, kind="stopped", answer="the same skipped step twice", ms=ms)
                    return 1, "refused", msg
                reasked.add(command.strip())
                record(s, kind="reasked", ms=ms)
                text = SKIPPED % command
                continue
            missing = persona.missing_word(command)
            if missing:
                # never offered to run: the model hears why and proposes
                # again -- it counts as a step, the cap stays DO_MAX_STEPS
                face.missing(n, command, hint, missing)
                record(s, kind="missing", ms=ms)
                text = "%s is not installed on this machine" % missing
                continue
            face.step(n, reply, box is not None)
            choice = "run"
            if box is None:
                try:
                    choice, command = face.confirm(reply, cwd)
                except EOFError:
                    record(s, kind="quit", ms=ms)       # nobody there: the run ends here
                    raise
            if choice == "quit":
                record(s, kind="quit", ms=ms)
                break
            if choice != "run":
                record(s, kind="skipped", ms=ms)
                skipped.add(command.strip())
                text = SKIPPED % command
                continue
            rc, tail = _step(face, command, shell, cwd, box, timeout)
            steps += 1
            face.ran(rc, hold(tail)[0])
            man = man_excerpt(command, rc, tail)
            if man:
                face.man(man)
            proof, prc, pchoice = (reply.get("proof") if rc == 0 else ""), None, ""
            if proof:
                # contract 4's proof line: one read-only check that the
                # step did what it claimed -- offered like a step (Enter
                # runs it; sandboxed it runs), on a leash, and only its
                # exit code goes back to the model: its output stays here
                pchoice, proof = face.proof(proof, cwd, box is not None, n)
                if pchoice == "run":
                    prc, ptail = _step(face, proof, shell, cwd, box, PROOF_TIMEOUT)
                    face.proof_ran(prc, hold(ptail)[0])
            # the record of what ran, on the thread now -- not inside the
            # next request, which a quit or the step limit never sends
            text, held, names = feedback(command, rc, tail, proposed, proof if prc is not None else "", prc, man)
            if held:
                print(textmod.held_line(held, names), file=sys.stderr, flush=True)
            extra = dict({"held": held} if held else {}, **({"man": len(man.encode("utf-8"))} if man else {}))
            record(s, kind="danger" if reply["danger"] else "cmd", command=command, hint=hint, rc=rc, ms=ms, **extra)
            land(cfg, thread, history, text, cwd)
            landed = True
            if pchoice == "quit":
                break
        else:
            face.cap()
            return 1, "cap", "step limit (%d) reached -- spark do again to continue" % DO_MAX_STEPS
    except EOFError:
        face.eof()
    face.stopped(steps)
    return 0, "quit", "stopped after %s" % _plural(steps, "step")


def _settle(face, box):
    """The review of a sandboxed run: (rc, reason, hint). Nothing changed:
    said, and the run goes. Else the face shows the changes and asks;
    yes applies them, discard drops them, anything else leaves the run
    waiting for spark do --review."""
    try:
        entries = sandbox.changes(box)
    except sandbox.SandboxError as e:
        face.unapplied(box, str(e), e.paths)
        return 1, "error", str(e)
    n = sandbox.count(entries)
    if not n:
        sandbox.discard(box)
        face.nothing(box)
        return 0, "done", "nothing changed"
    answer = face.review(box, entries, n)
    if answer == "yes":
        return _apply(face, box)
    if answer == "discard":
        sandbox.discard(box)
        face.discarded(box)
        return 0, "done", "discarded run %s; nothing was applied" % box["id"]
    face.waits(box, n)
    return 0, "quit", "the run waits: spark do --review %s" % box["id"]


def _leave(face, box):
    """A run stopped before its review (Ctrl-C, SIGTERM, the brain gone):
    what the copy holds waits for spark do --review; an untouched copy
    goes. True when it waits."""
    try:
        n = sandbox.count(sandbox.changes(box))
    except sandbox.SandboxError:
        n = 1
    if not n:
        sandbox.discard(box)
        return False
    face.waits(box, n)
    return True


def _apply(face, box):
    """sandbox.apply, told: (rc, reason, hint). A refusal (a git lock, a
    conflict, a project that does not open) applies nothing and leaves the
    run waiting."""
    try:
        n, problems = sandbox.apply(box)
    except (sandbox.SandboxError, OSError) as e:
        face.unapplied(box, str(e), getattr(e, "paths", []))
        return 1, "error", "%s -- the run waits: spark do --review %s" % (e, box["id"])
    face.applied(box, n, problems)
    return 0, "done", "applied %s" % _plural(n, "change")


def _detach_lock():
    """The one detached run: an flock on STATE/runs/detach.lock, held
    until this process ends (the kernel lets go when it dies, so no stale
    lock outlives a killed run). None while another run holds it."""
    import fcntl
    sandbox._mkdirs(sandbox.RUNS_DIR)
    fd = os.open(os.path.join(sandbox.RUNS_DIR, DETACH_LOCK),
                 os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


def _options(args):
    """(flags, words): the leading options, then the goal's words; `--`
    ends the options. (None, the word) for an option spark do does not
    take -- a goal that starts with - comes after `--`."""
    flags, i = [], 0
    while i < len(args):
        a = args[i]
        if a == "--":
            i += 1
            break
        if not a.startswith("-") or a == "-":
            break
        if a not in OPTIONS:
            return None, a
        flags.append(a)
        i += 1
    return flags, args[i:]


def cmd_do(args):
    if not args or args[0] in ("-h", "--help", "help"):
        say(DO_USAGE.rstrip() % (MARK, STEP_TIMEOUT, DO_MAX_STEPS))
        return 0 if args else 2
    flags, words = _options(args)
    if flags is None:
        say("%s do -- no option %s: spark do -h lists them; spark do -- <words> for a goal that starts with -"
            % (MARK, words))
        return 2
    if "-h" in flags or "--help" in flags:
        say(DO_USAGE.rstrip() % (MARK, STEP_TIMEOUT, DO_MAX_STEPS))
        return 0
    verbs = [f for f in flags if f in ("--review", "--accept", "--discard")]
    if verbs:
        return _runs_verb(flags, verbs, words)
    goal = " ".join(words).strip()
    if not goal:
        say(DO_USAGE.rstrip() % (MARK, STEP_TIMEOUT, DO_MAX_STEPS))
        return 2
    boxed, detach = "--sandbox" in flags, "--detach" in flags
    if detach and not boxed:
        say("%s do -- --detach runs sandboxed only: spark do --sandbox --detach <words>" % MARK)
        return 2
    if not detach and not sys.stdin.isatty() and os.environ.get(STDIN_HOOK) != "1":
        if boxed:
            die("spark do --sandbox asks yes before it applies -- run it in a terminal, or add --detach")
        die("spark do confirms every step -- run it in a terminal")
    if os.environ.get(STDIN_HOOK) == "1":
        sys.stderr.write(STDIN_BANNER + "\n")
        sys.stderr.flush()
    if not detach:
        return _start(_Terminal(), goal, boxed, STEP_TIMEOUT if boxed else None)
    lock = _detach_lock()
    if lock is None:
        say("%s do -- a detached run is running already: one at a time" % MARK)
        return 2
    try:
        return _start(_Terminal(detach=True), goal, True, STEP_TIMEOUT)
    finally:
        os.close(lock)


def _start(face, goal, boxed, timeout):
    """Resolve the brain, make the sandbox's run and the thread, drive the
    run, and settle a sandboxed one: the exit code."""
    cfg = config.load()
    cwd, shell = os.getcwd(), os.path.basename(os.environ.get("SHELL") or "sh")
    try:
        url, model, _forge = wire.resolve_brain(cfg)
    except wire.BrainError as e:
        die(e.hint)
    box, mcwd, text = None, cwd, goal
    if boxed:
        good, detail = sandbox.probe()
        if not good:
            fix = sandbox.install_hint()
            return face.refuse(detail + (" -- " + fix if fix else ""))
        try:
            box = sandbox.new_run(cwd, "")
        except sandbox.SandboxError as e:
            return face.refuse(str(e))
        mcwd = sandbox.step(box, _shell_path(shell), "true")[1]    # macOS: the clone
        text = goal + "\n\n" + SANDBOX_NOTE
        # a SIGTERM (a timer's stop, a client's) ends the run as Ctrl-C does:
        # the step's own process group goes with it
        signal.signal(signal.SIGTERM, lambda *_a: sys.exit(143))
    elif timeout is not None:
        signal.signal(signal.SIGTERM, lambda *_a: sys.exit(143))
    thread = forge.new_thread(cfg)
    if box is not None:
        box["thread"] = thread or ""
        sandbox.mark(box, "waiting")      # the run's record names its thread
    face.begin(_driver(cfg, url, model, _forge), box, cwd, thread)
    try:
        rc, reason, hint = _drive(face, cfg, thread, goal, text, shell, mcwd, box, timeout)
    except (KeyboardInterrupt, SystemExit):
        if box is not None:
            _leave(face, box)
        raise
    if box is not None and reason != "error":
        rc, reason, hint = _settle(face, box)
    elif box is not None and _leave(face, box):
        hint += " -- the run waits: spark do --review %s" % box["id"]
    face.end(reason, hint, rc)
    _prune(cfg)
    return rc


# ------------------------------------------------------------------ runs
def _goal_words(run, n=8):
    """The first words of a run's goal, read from its sealed thread (the
    run's record keeps no words); '-' when the thread is gone or shut."""
    tid = run.get("thread") or ""
    if not forge.valid_id(tid):
        return "-"
    msgs = [m for m in forge.load(tid) if m.get("role") == "user"]
    if not msgs:
        return "-"
    words = (msgs[0].get("text") or "").split("\n", 1)[0].split()
    return " ".join(words[:n]) + (" ..." if len(words) > n else "")


def _age(start_ns):
    import time
    secs = max(0, int(time.time() - start_ns / 1e9))
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if secs >= size:
            return "%d%s" % (secs // size, unit)
    return "%ds" % secs


def _runs_verb(flags, verbs, words):
    """--review [ID], --accept ID, --discard ID: the runs waiting."""
    verb = verbs[0]
    if len(verbs) > 1 or len(flags) > 1 or len(words) > 1 or (verb != "--review" and len(words) != 1):
        say("%s do -- %s takes one run's id (spark do --review lists them)" % (MARK, verb))
        return 2
    if verb == "--review" and not words:
        return _list_runs()
    try:
        box = sandbox.load(words[0])
    except sandbox.SandboxError as e:
        say("%s do -- %s" % (MARK, e))
        return 2
    if box["state"] != "waiting":
        say("%s do -- run %s is %s already" % (MARK, box["id"], box["state"]))
        return 2
    face = _Terminal()
    if verb == "--discard":
        sandbox.discard(box)
        face.discarded(box)
        return 0
    if verb == "--accept":
        return _apply(face, box)[0]
    if not sys.stdin.isatty() and os.environ.get(STDIN_HOOK) != "1":
        say("%s do -- --review asks yes at a terminal; spark do --accept %s applies without asking"
            % (MARK, box["id"]))
        return 2
    return _settle(face, box)[0]


def _list_runs():
    waiting = sandbox.runs()
    if not waiting:
        say("no sandboxed run waits for review")
        return 0
    for r in waiting:
        try:
            n = sandbox.count(sandbox.changes(r))
        except sandbox.SandboxError:
            n = 0
        say("%s  %4s  %-11s %s" % (r["id"], _age(r["start"]), _plural(n, "change"), _goal_words(r)))
    say("spark do --review ID shows one and asks yes; --accept ID applies it, --discard ID drops it")
    return 0


def _prune(cfg):
    session.prune(cfg)
    forge.prune(cfg)
