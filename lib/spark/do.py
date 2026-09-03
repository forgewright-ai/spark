# spark.do -- a task done one confirmed command at a time (`spark do`).
#
# The model proposes ONE command per step (kind=cmd) with a hint, or says
# the goal is met (kind=done). Nothing runs until the user says so at the
# prompt: Enter runs it, e edits it first, s skips it, q quits; a step the
# model or persona.is_dangerous flags runs only on the literal `yes`. The
# output of each step (its last 4 kB) is the next user message, so the
# model reads what happened before proposing the next one.
#
# propose() and run() take values and return values -- no terminal -- so
# the prompt and (later) the page share one code path. cmd_do is the
# terminal around them.

import os
import re
import subprocess
import sys

from . import MARK, config, die, glyph, say
from . import forge, persona, session, wire

DO_MAX_STEPS = 8
OUTPUT_TAIL = 4000          # what a step's output sends at most: its last 4 kB
NO_OUTPUT = "(no output)"
SKIPPED = "The user skipped this step."
STDIN_HOOK = "SPARK_DO_STDIN"   # =1: confirmations come from stdin lines (tests)

DO_SCHEMA = dict(persona.LINE_SCHEMA, properties=dict(
    persona.LINE_SCHEMA["properties"], kind={"type": "string", "enum": ["cmd", "done"]}))

DO_USAGE = """%s do -- a task, step by step

  spark do <words>     the goal; one command at a time, you confirm each

  Every step:  Enter runs it, e edits it first, s skips it, q quits.
  A step that can destroy data runs only when you type yes.
  At most %d steps per run; the output of each (last 4 kB) goes back
  to the model. Every step is recorded (spark last, spark history).
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


def propose(cfg, thread, text, shell, cwd, history=None, brain=None):
    """One step, no terminal: (reply, ms). reply is {"kind": cmd|done,
    "command", "hint", "danger"} with danger normalised (the model's flag
    or persona.is_dangerous). `history` is the run so far as chat
    messages, extended in place; None reads the thread from disk. Both
    messages land on the thread. `brain` goes to the Session (the FORGE's
    own upstream). Never runs anything. Raises BrainError."""
    if history is None:
        history = forge.history(thread)
    s = session.Session(cfg, "do", shell, cwd, history, brain)
    raw, ms = s.ask_json(text, DO_SCHEMA)
    command = " ".join(str(raw.get("command") or "").split())
    hint = " ".join(str(raw.get("hint") or "").split())
    kind = "cmd" if raw.get("kind") == "cmd" and command else "done"
    reply = {"kind": kind, "command": command if kind == "cmd" else "", "hint": hint,
             "danger": kind == "cmd" and (bool(raw.get("danger")) or persona.is_dangerous(command))}
    user = persona.user_message(text, cwd)
    history.extend([{"role": "user", "content": user}, {"role": "assistant", "content": shown(reply)}])
    forge.append(cfg, thread, "user", text, mode="do", cwd=cwd)
    forge.append(cfg, thread, "assistant", shown(reply), kind="danger" if reply["danger"] else kind)
    return reply, ms


def run(command, shell, cwd="", echo=True):
    """Run one step through `shell -c`, its output echoed live to stdout
    (echo=False keeps quiet), stderr folded in. (rc, the last 4 kB)."""
    try:
        p = subprocess.Popen([shell, "-c", command], cwd=cwd or None, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except OSError as e:
        return 127, "%s: %s" % (shell, e.strerror or e)
    tail = ""
    with p.stdout:
        for raw in p.stdout:
            line = raw.decode("utf-8", errors="replace")
            if echo:
                sys.stdout.write(line)
                sys.stdout.flush()
            tail = (tail + line)[-OUTPUT_TAIL:]
    return p.wait(), tail


def feedback(command, rc, tail):
    """The next user message: what the step printed, and how it ended."""
    return "Output of `%s` (exit %d):\n%s" % (command, rc, tail.rstrip("\n") or NO_OUTPUT)


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


def _confirm(reply):
    """What the user wants for this step: run | edit | skip | quit."""
    if reply["danger"]:
        answer = input("  this can destroy data -- type yes to run it: ").strip()
        return "run" if answer == "yes" else "skip"
    answer = input("  Enter runs it, e edits, s skips, q quits: ").strip().lower()
    return {"": "run", "e": "edit", "s": "skip", "q": "quit"}.get(answer, "skip")


def cmd_do(args):
    if not args or args[0] in ("-h", "--help", "help"):
        say(DO_USAGE.rstrip() % (MARK, DO_MAX_STEPS))
        return 0 if args else 2
    if not sys.stdin.isatty() and os.environ.get(STDIN_HOOK) != "1":
        die("spark do confirms every step -- run it in a terminal")
    goal = " ".join(args)
    cfg = config.load()
    cwd, shell = os.getcwd(), os.path.basename(os.environ.get("SHELL") or "sh")
    try:
        url, model, _forge = wire.resolve_brain(cfg)
    except wire.BrainError as e:
        die(e.hint)
    thread = forge.new_thread(cfg)
    say("%s driving with %s (a silence is the model thinking)" % (glyph("hammer"), _driver(cfg, url, model, _forge)))
    history, text, steps, seen = [], goal, 0, []

    def record(**fields):
        session.record(cfg, backend=url, model=model, mode="do", thread=thread, line=goal, **fields)

    try:
        for n in range(1, DO_MAX_STEPS + 1):
            seen.append(text)
            try:
                reply, ms = propose(cfg, thread, text, shell, cwd, history)
            except wire.BrainError as e:
                die(e.hint)
            if reply["kind"] == "done":
                bad = unchecked(reply["hint"], seen)
                say("%s done  %s" % (glyph("warn" if bad else "ok"), reply["hint"]))
                if bad:
                    say("  unchecked: no command produced %s -- believe the outputs above" % ", ".join(bad))
                record(kind="done", answer=reply["hint"], ms=ms)
                _prune(cfg)
                return 0
            command, hint = reply["command"], reply["hint"]
            missing = persona.missing_word(command)
            if missing:
                # never offered to run: the model hears why and proposes
                # again -- it counts as a step, the cap stays DO_MAX_STEPS
                from .cli import _one_line
                say("%s %d  %s   %s" % (glyph("warn"), n, command,
                                        _one_line("%s: not on this machine -- %s" % (missing, hint))))
                text = "%s is not installed on this machine" % missing
                continue
            say("%s %d  %s   %s" % (glyph("warn") if reply["danger"] else glyph("hammer"), n, command, hint))
            choice = _confirm(reply)
            if choice == "edit":
                command = _edit(command)
                reply["danger"] = bool(reply["danger"]) or persona.is_dangerous(command)
                if reply["danger"] and _confirm(reply) != "run":
                    choice = "skip"
            if choice == "quit":
                break
            if choice == "skip":
                text = SKIPPED
                continue
            rc, tail = run(command, shell, cwd)
            steps += 1
            record(kind="danger" if reply["danger"] else "cmd", command=command, hint=hint, rc=rc, ms=ms)
            text = feedback(command, rc, tail)
        else:
            say("%s step limit (%d) reached -- spark do again to continue" % (glyph("warn"), DO_MAX_STEPS))
            _prune(cfg)
            return 1
    except EOFError:
        say()
    say("%s stopped after %d step%s" % (glyph("hammer"), steps, "" if steps == 1 else "s"))
    _prune(cfg)
    return 0


def _prune(cfg):
    session.prune(cfg)
    forge.prune(cfg)
