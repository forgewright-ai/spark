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

import os
import re
import signal
import subprocess
import sys
import threading

from . import MARK, config, die, glyph, paint, say
from . import bar, forge, persona, session, wire
from . import text as textmod

DO_MAX_STEPS = 8
OUTPUT_TAIL = 4000          # what a step's output sends at most: its last 4 kB
PROOF_TIMEOUT = 30          # seconds a proof may run before it is killed (rc 124)
NO_OUTPUT = "(no output)"
SKIPPED = "The user skipped this step."
STDIN_HOOK = "SPARK_DO_STDIN"   # =1: confirmations come from stdin lines (tests)
# said once on stderr when the hook is on, before any step is offered: a
# transcript must show the confirmations were a harness's, not a person's
STDIN_BANNER = "spark do: confirmations come from stdin (SPARK_DO_STDIN) -- a harness, not a person"
# a control character in the model's command or proof: a terminal escape
# can draw a benign fake over what Enter would run, so the reply is
# refused whole -- it becomes a `done` with this hint
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
REFUSED_CONTROL = "the model's command carried control characters -- refused"

DO_SCHEMA = dict(persona.LINE_SCHEMA, properties=dict(
    persona.LINE_SCHEMA["properties"], kind={"type": "string", "enum": ["cmd", "done"]}))

DO_USAGE = """%s do -- a task, step by step

  spark do <words>     the goal; one command at a time, you confirm each

  Every step:  Enter runs it, e edits it first, s skips it, q quits.
  A step that can destroy data (sudo too) runs only when you type yes.
  After a step, its proof -- one read-only check -- is offered the same
  way; only its exit code goes back to the model, never its output.
  At most %d steps per run; the output of each (last 4 kB) goes back
  to the model. Every step is recorded as it ran (spark last, history).
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


def propose(cfg, thread, text, shell, cwd, history=None, brain=None, landed=False):
    """One step, no terminal: (reply, ms). reply is {"kind": cmd|done,
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
    here. `brain` goes to the Session (the FORGE's own upstream). Never
    runs anything. Raises BrainError."""
    if history is None:
        history = forge.history(thread)
    s = session.Session(cfg, "do", shell, cwd, history[:-1] if landed else history, brain)
    raw, ms = s.ask_json(text, DO_SCHEMA)
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
    return reply, ms


def land(cfg, thread, history, text, cwd):
    """One user message onto the run, now: `history` in place (with the
    [cwd] line the wire carries) and the thread on disk. cmd_do lands a
    step's feedback here the moment the step ran, before any next
    propose, so the record holds what ran even when the run stops there;
    the next propose(landed=True) rides it without appending it again."""
    history.append({"role": "user", "content": persona.user_message(text, cwd)})
    forge.append(cfg, thread, "user", text, mode="do", cwd=cwd)


def run(command, shell, cwd="", echo=True, timeout=None):
    """Run one step through `shell -c`, its output echoed live to stdout
    (echo=False keeps quiet), stderr folded in. (rc, the last 4 kB).
    `timeout` (seconds) is a leash: the command runs in its own process
    group and the whole group is killed when it expires -- rc 124 with
    the tail so far. The proof runs on one; a step does not."""
    try:
        p = subprocess.Popen([shell, "-c", command], cwd=cwd or None, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             start_new_session=timeout is not None)
    except OSError as e:
        return 127, "%s: %s" % (shell, e.strerror or e)
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
    with p.stdout:
        for raw in p.stdout:
            line = raw.decode("utf-8", errors="replace")
            if echo:
                sys.stdout.write(line)
                sys.stdout.flush()
            tail = (tail + line)[-OUTPUT_TAIL:]
    rc = p.wait()
    if timer is not None:
        timer.cancel()
    return (124 if expired else rc), tail


def feedback(command, rc, tail, proposed="", proof="", prc=None):
    """The record of a step as it ran, and the next user message: the
    command that ran (`edited from` the proposal when the user changed
    it), what it printed, how it ended, and the proof's exit code alone
    when one ran -- never the proof's output."""
    edited = ("; edited from `%s`" % proposed) if proposed and proposed != command else ""
    s = "Output of `%s` (exit %d%s):\n%s" % (command, rc, edited, tail.rstrip("\n") or NO_OUTPUT)
    if proof and prc is not None:
        s += "\n\nProof `%s` exited %d." % (proof, prc)
    return s


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


def _mark():
    """the answer mark, in the accent at a tty (plain piped or unset)"""
    return paint(glyph("hammer"), "accent", sys.stdout)


def cmd_do(args):
    if not args or args[0] in ("-h", "--help", "help"):
        say(DO_USAGE.rstrip() % (MARK, DO_MAX_STEPS))
        return 0 if args else 2
    if not sys.stdin.isatty() and os.environ.get(STDIN_HOOK) != "1":
        die("spark do confirms every step -- run it in a terminal")
    if os.environ.get(STDIN_HOOK) == "1":
        sys.stderr.write(STDIN_BANNER + "\n")
        sys.stderr.flush()
    goal = " ".join(args)
    cfg = config.load()
    cwd, shell = os.getcwd(), os.path.basename(os.environ.get("SHELL") or "sh")
    try:
        url, model, _forge = wire.resolve_brain(cfg)
    except wire.BrainError as e:
        die(e.hint)
    thread = forge.new_thread(cfg)
    say("%s driving with %s (a silence is the model thinking)" % (_mark(), _driver(cfg, url, model, _forge)))
    history, text, steps, seen, landed = [], goal, 0, [], False

    def record(**fields):
        session.record(cfg, backend=url, model=model, mode="do", thread=thread, line=goal, **fields)

    try:
        for n in range(1, DO_MAX_STEPS + 1):
            seen.append(text)
            try:
                with textmod.Busy(sys.stderr):        # the pulse while the model proposes
                    reply, ms = propose(cfg, thread, text, shell, cwd, history, landed=landed)
            except wire.BrainError as e:
                bar.prompt_state(cfg, ai="down")
                die(e.hint)
            landed = False
            if reply["kind"] == "done":
                bad = unchecked(reply["hint"], seen)
                say("%s done  %s" % (glyph("warn" if bad else "ok"), reply["hint"]))
                if bad:
                    say("  unchecked: no command produced %s -- believe the outputs above" % ", ".join(bad))
                record(kind="done", answer=reply["hint"], ms=ms)
                _prune(cfg)
                return 0
            proposed, command, hint = reply["command"], reply["command"], reply["hint"]
            missing = persona.missing_word(command)
            if missing:
                # never offered to run: the model hears why and proposes
                # again -- it counts as a step, the cap stays DO_MAX_STEPS
                from .cli import _one_line
                say("%s %d  %s   %s" % (glyph("warn"), n, command,
                                        _one_line("%s: not on this machine -- %s" % (missing, hint))))
                text = "%s is not installed on this machine" % missing
                continue
            if reply["danger"]:
                say(paint("%s %d  %s   %s" % (glyph("warn"), n, command, hint), "warn", sys.stdout))
            else:
                say("%s %d  %s   %s" % (_mark(), n, command, hint))
            choice = _confirm(reply, cwd)
            if choice == "edit":
                command = _edit(command)
                reply["danger"] = bool(reply["danger"]) or persona.is_dangerous(command)
                if reply["danger"] and _confirm(reply, cwd) != "run":
                    choice = "skip"
            if choice == "quit":
                break
            if choice == "skip":
                text = SKIPPED
                continue
            rc, tail = run(command, shell, cwd)
            steps += 1
            record(kind="danger" if reply["danger"] else "cmd", command=command, hint=hint, rc=rc, ms=ms)
            proof, prc, pchoice = (reply.get("proof") if rc == 0 else ""), None, ""
            if proof:
                # contract 4's proof line: one read-only check that the
                # step did what it claimed -- offered like a step (Enter
                # runs it), run on a leash, and only its exit code goes
                # back to the model: its output stays on this screen
                say("%s    proof: %s" % (_mark(), proof))
                try:
                    pchoice = _confirm({"danger": False, "command": proof}, cwd)
                    if pchoice == "edit":
                        proof = _edit(proof)
                        if not persona.proof_ok(proof):
                            say("  %s not a read-only proof -- skipped" % glyph("warn"))
                            pchoice = "skip"
                except EOFError:
                    pchoice = "quit"        # nobody there; the step still lands below
                if pchoice == "run":
                    prc, _ptail = run(proof, shell, cwd, timeout=PROOF_TIMEOUT)
                    say("%s    proof -> %s" % (_mark(), "ok" if prc == 0 else "exit %d" % prc))
            # the record of what ran, on the thread now -- not inside the
            # next request, which a quit or the step limit never sends
            text = feedback(command, rc, tail, proposed, proof if prc is not None else "", prc)
            land(cfg, thread, history, text, cwd)
            landed = True
            if pchoice == "quit":
                break
        else:
            say("%s step limit (%d) reached -- spark do again to continue" % (glyph("warn"), DO_MAX_STEPS))
            _prune(cfg)
            return 1
    except EOFError:
        say()
    say("%s stopped after %d step%s" % (_mark(), steps, "" if steps == 1 else "s"))
    _prune(cfg)
    return 0


def _prune(cfg):
    session.prune(cfg)
    forge.prune(cfg)
