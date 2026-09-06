# spark.cli -- the client subcommands: line (what the widgets call), ask,
# explain, last, brain, status, off, on, history, and the thin dispatch to
# soul / remember / forget / memory / chat / do (imported only when called).

import os
import re
import sys
import time

from . import CONFIG_DIR, MARK, OFF_FLAG, REPO, STATE_DIR, WIDGETS_DIR, config, die, glyph, paged, say, state_dir
from . import engine, forge, ledger, persona, session, version, wire

HINT_COLS = 80
STDIN_TAIL = 6000          # what `explain` sends at most: the last 6 kB
# spark edit (contract 10): what the editor sends at most
EDIT_BEFORE, EDIT_AFTER = 4000, 2000   # a completion: around the cursor
EDIT_MAX = 12000                        # a rewrite: the whole text, or nothing
EDIT_READ = 800                         # the reading before a question
EDIT_SEL_MAX = 12000                    # a selection inside a ?: whole up to this, else head + tail
EDIT_WINDOW = 16000                     # a ? with --sel: the selection and the file around it
EDIT_TIMEOUT = 180                      # a big selection takes a while to read

# Grammar rule 4: every verb answers -h first, signed per contract 8.
LINE_USAGE = """spark line -- the widget's protocol (contract 4)

  spark line --cwd D --shell S   reads the prompt buffer on stdin; prints
                                 cmd|danger<TAB>command, answer or error,
                                 then the hint / answer / reason
"""
EXPLAIN_USAGE = """spark explain -- what went wrong in the piped output, and the fix

  cmd 2>&1 | explain [words]  reads stdin (the last 6 kB); explain on PATH
                              is a symlink to spark
"""
EDIT_USAGE = """spark edit -- the editor's protocol (contract 10): the text on stdin

  spark edit --at N           prints what goes at byte offset N (a completion)
  spark edit <words>          prints the text rewritten as the words ask
  spark edit ? [words]        answers about the text; ? alone reviews it
  --type FT                   the editor's filetype, a hint (markdown, python)
  --name NAME                 the file's name, a hint -- never its path
  --about TEXT                what the author says the text is, when it
                              should not guess ("a novel chapter")
  --part                      the text is a selection from a larger file:
                              a rewrite replaces exactly that part
  --sel A B                   ?: stdin is the whole file; the question is
                              about bytes A..B, the file around it context
  --thread ID                 ?: keep the exchange under ID (yours to name,
                              [A-Za-z0-9_-]); the same ID again continues it
  --decline --name NAME       keep the note on stdin as declined for NAME: a
                              later ? about NAME is told not to raise it

  raw streamed text: no mark, no wrap, a code fence around the answer is
  removed; exit 1 when nothing came in or no brain answers. In micro,
  Alt-s (spark shell on). From a pipe: spark edit fix grammar < draft.md
"""
LAST_USAGE = """spark last -- the last exchange, with its tok/s

  spark last                  the newest turn: the line, the answer, the
                              model that answered and its speed
"""
STATUS_USAGE = """spark status -- the full picture: brain, widget, service, soul, memory, last

  spark status                what bare spark shows (SITE_QUIET_START=yes makes
                              bare spark one line; spark status stays full)
"""
BRAIN_USAGE = """spark brain -- what answers right now: a FORGE or a llama-server

  spark brain                 the url, the model, the roles it serves
  spark brain --porcelain     url<TAB>model<TAB>forge|model; exit 1 when none
  spark brain --fresh         ignore the cached answer
"""
OFF_USAGE = """spark off -- silence the prompt widget, every pane at once

  spark off                   Enter is the shell's again; Esc s and
                              spark <words> still work; spark on restores
"""
ON_USAGE = """spark on -- the prompt widget answers again

  spark on                    ? words and words? go to the model again
"""
HISTORY_USAGE = """spark history -- the threads kept on this machine

  spark history               where they live, and the newest five
  spark history clear         remove every turn and thread kept so far
"""
VER_USAGE = """spark ver -- logo, version, credits

  spark ver                   the banner, the version (from git), the credits
"""


def _help(args, usage):
    """True (and the usage printed) when args ask for help."""
    if args[:1] and args[0] in ("-h", "--help", "help"):
        say(usage.rstrip())
        return True
    return False


def _one_line(s, width=HINT_COLS):
    s = " ".join((s or "").split())
    return s if len(s) <= width else s[:width - 1] + "…"


def _shell_default():
    return os.path.basename(os.environ.get("SHELL") or "sh")


# ------------------------------------------------------------------- line
def _last_proposed(history):
    """The last command a thread's assistant turns proposed: the text
    between the first backticks of the newest cmd-shaped message."""
    for m in reversed(history or []):
        c = m.get("content", "")
        if m.get("role") == "assistant" and c.startswith("`") and "`" in c[1:]:
            return c[1:1 + c[1:].index("`")]
    return None


def cmd_line(args):
    """Contract 4. stdin = the prompt buffer. stdout line 1 = cmd<TAB>command
    | danger<TAB>command | answer | error; line 2 = hint / answer / reason."""
    if _help(args, LINE_USAGE):
        return 0
    cwd, shell = "", _shell_default()
    it = iter(args)
    for a in it:
        if a == "--cwd":
            cwd = next(it, "")
        elif a == "--shell":
            shell = next(it, shell)
    text = sys.stdin.read().strip()
    more = text.startswith("??")            # `?? words`: go on with the newest thread
    if more:
        text = text[2:].strip()
    elif text.startswith("? "):
        text = text[2:].strip()
    elif text.startswith("?"):
        text = text[1:].strip()
    if text.endswith("?"):
        text = text[:-1].rstrip() + "?"
    if not text.strip("? "):
        say("error")
        say("nothing to ask")
        return 1
    cfg = config.load()
    thread, history = forge.pick(cfg, more)
    try:
        s = session.Session(cfg, "line", shell, cwd, history)
        reply, ms = s.ask_json(text)
    except wire.BrainError as e:
        say("error")
        say(_one_line(e.hint))
        return 1
    kind = reply.get("kind")
    command = _one_line(reply.get("command", ""), 1000)
    hint = _one_line(reply.get("hint", ""))
    if kind == "cmd" and command:
        # the head-word guard: a command whose head word nothing here
        # answers to is re-asked once; failing that, the hint says so.
        # Never blocks, never errors -- the user still sees a reply.
        missing = persona.missing_word(command)
        if missing:
            try:
                s.history.extend([{"role": "user", "content": persona.user_message(text, cwd)},
                                  {"role": "assistant", "content": "`%s` -- %s" % (command, hint)}])
                retry, ms2 = s.ask_json("%s is not installed on this machine; use only commands that exist here." % missing)
                ms += ms2
                c2 = _one_line(retry.get("command", ""), 1000)
                if retry.get("kind") == "cmd" and c2 and not persona.missing_word(c2):
                    reply, command, missing = retry, c2, ""
                    hint = _one_line(retry.get("hint", ""))
            except wire.BrainError:
                pass
            if missing:
                hint = _one_line("%s: not on this machine -- %s" % (missing, hint))
        if more and command == _last_proposed(history):
            # the repair guard: a ?? turn must not re-serve the very command
            # the user just said failed. One re-ask; then honesty.
            try:
                s.history.extend([{"role": "user", "content": persona.user_message(text, cwd)},
                                  {"role": "assistant", "content": "`%s` -- %s" % (command, hint)}])
                retry, ms2 = s.ask_json("that exact command was already tried and failed; propose a different one.")
                ms += ms2
                c3 = _one_line(retry.get("command", ""), 1000)
                if retry.get("kind") == "cmd" and c3 and c3 != command:
                    reply, command = retry, c3
                    hint = _one_line(retry.get("hint", ""))
                else:
                    hint = _one_line("already tried above -- %s" % hint)
            except wire.BrainError:
                hint = _one_line("already tried above -- %s" % hint)
        flagged = bool(reply.get("danger")) or persona.is_dangerous(command)
        kind = "danger" if flagged else "cmd"
        say(kind + "\t" + command)
        say(hint)
        shown = "`%s` -- %s" % (command, hint)
        s.record(kind=kind, line=text, command=command, hint=hint, ms=ms, thread=thread)
    else:
        kind = "answer"
        shown = _one_line(reply.get("hint") or reply.get("command") or "")
        say("answer")
        say(shown)
        s.record(kind=kind, line=text, answer=shown, ms=ms, thread=thread)
    forge.append(cfg, thread, "user", text, mode="line", cwd=cwd)
    forge.append(cfg, thread, "assistant", shown, kind=kind)
    _prune(cfg)
    return 0


def _prune(cfg):
    session.prune(cfg)
    forge.prune(cfg)


# ---------------------------------------------------------------- ask etc.
def _stdin_context():
    if sys.stdin.isatty():
        return ""
    data = sys.stdin.read()
    if len(data) > STDIN_TAIL:
        data = "[... %d chars cut ...]\n" % (len(data) - STDIN_TAIL) + data[-STDIN_TAIL:]
    return data


def stream_turn(cfg, mode, text, files=(), context="", thread=None, line=None, mark=True):
    """One turn through forge.reply, wrapped to the terminal (80 when
    piped): the mark (mark=False keeps a conversation bare -- a dialog
    needs no mark), the answer as it streams, a trailing newline. Returns
    the thread id. RefError, BrainError and KeyboardInterrupt pass through
    -- the wrap is closed first so a half-printed answer still ends in a
    newline; forge.reply keeps the raw text for the thread record."""
    from . import text as textmod
    wrap = textmod.Wrap(sys.stdout, mark=mark)
    try:
        thread, _, _ = forge.reply(cfg, thread, text, files, os.getcwd(), _shell_default(), mode, wrap.feed, context, line)
    except (wire.BrainError, KeyboardInterrupt):
        wrap.close()
        raise
    wrap.close()
    _prune(cfg)
    return thread


def _stream(mode, text, files=(), context="", thread=None, line=None, mark=True):
    """stream_turn as a command: a refusal or a dead brain ends with exit 1."""
    try:
        stream_turn(config.load(), mode, text, files, context, thread, line, mark)
    except (forge.RefError, wire.BrainError) as e:
        die(e.hint)
    return 0


def cmd_ask(words):
    words, paths = forge.refs(words)
    q = " ".join(words).strip()
    ctx = _stdin_context()
    if not q and not ctx and not paths:
        return cmd_status([])
    mode = "explain" if ctx and not q else "ask"
    return _stream(mode, q, paths, ctx, line=None if q or paths else "[explain]")


def cmd_explain(words):
    if _help(words, EXPLAIN_USAGE):
        return 0
    ctx = _stdin_context()
    if not ctx:
        die("explain reads stdin -- cmd 2>&1 | explain")
    return _stream("explain", " ".join(words).strip(), context=ctx, line="[explain] " + " ".join(words))


# ------------------------------------------------------------------- edit
def _edit_args(args):
    """(options, words) -- ValueError names a flag that lacks its value."""
    opts = {"type": "", "name": "", "about": "", "at": None, "part": False, "sel": None, "thread": "", "decline": False}
    words, rest = [], list(args)
    while rest:
        a = rest.pop(0)
        if a == "--part":
            opts["part"] = True
        elif a == "--decline":
            opts["decline"] = True
        elif a == "--sel":
            if len(rest) < 2:
                raise ValueError(a)
            opts["sel"] = (rest.pop(0), rest.pop(0))
        elif a in ("--type", "--name", "--about", "--at", "--thread"):
            if not rest:
                raise ValueError(a)
            opts[a[2:]] = rest.pop(0)
        else:
            words.append(a)
    return opts, words


def _sha(data):
    import hashlib
    return hashlib.sha256(data.encode("utf-8", "replace")).hexdigest()[:16]


def _edit_label(name, ftype, part=False):
    what = "File %s" % name if name else "Text"
    if part:
        what = "Selected part of %s" % name if name else "Selected text"
    return what + (" (%s):" % ftype if ftype else ":")


def _edit_window(data, a, b):
    """The context of a ? about a selection: the selection whole (head +
    cut mark + tail past EDIT_SEL_MAX) between two mark lines the brief
    knows, and as much of the file around it as EDIT_WINDOW leaves,
    split evenly, a side's unused room going to the other; a cut mark
    where the file goes on."""
    sel = data[a:b]
    if len(sel) > EDIT_SEL_MAX:
        sel = sel[:4000] + "\n[... %d chars cut ...]\n" % (len(sel) - EDIT_SEL_MAX) + sel[-(EDIT_SEL_MAX - 4000):]
    room = max(0, EDIT_WINDOW - len(sel))
    half = room // 2
    before_all, after_all = data[:a], data[b:]
    before = before_all[-(half + max(0, half - len(after_all))):] if room else ""
    after = after_all[:room - len(before)] if room else ""
    if len(before) < len(before_all):
        before = "[... %d chars cut ...]\n" % (len(before_all) - len(before)) + before
    if len(after) < len(after_all):
        after = after + "\n[... %d chars cut ...]" % (len(after_all) - len(after))
    return "%s\n[selection starts]\n%s\n[selection ends]\n%s" % (before, sel, after)


def _edit_reading(cfg, data):
    """(`You read this as: LANGUAGE, KIND.\n`, `\n\nAnswer in LANGUAGE.`) --
    the model's own reading of the text's first 800 chars
    (persona.MODE_EDIT_READ), restated to it above the text, and the
    language it named repeated as the last line of the request: a small
    model answers a Portuguese draft in English otherwise, whatever the
    brief says. Any failure is two empty strings: the question goes on."""
    try:
        s = session.Session(cfg, "edit-read", _shell_default(), "", role="spark")
        reply, _ms = s.ask_json(data[:EDIT_READ], persona.READ_SCHEMA, max_tokens=30, timeout=EDIT_TIMEOUT)
        lang, kind = [" ".join(str(reply.get(k, "")).split()) for k in ("language", "kind")]
    except Exception:
        return "", ""
    parts = [p for p in (lang, kind) if p]
    if not parts:
        return "", ""
    tail = "\n\nAnswer in %s." % lang if lang and lang.lower() not in ("code", "source code", "none", "n/a") else ""
    return "You read this as: %s.\n" % ", ".join(parts), tail


def cmd_edit(args):
    """The editor's protocol: the text on stdin, raw text out (no mark, no
    wrap -- the text goes back into a buffer). Three kinds by the words:
    --at N completes at that byte offset, words rewrite, `?` asks. No
    thread is kept and no path is sent: the turn record is numbers only."""
    if _help(args, EDIT_USAGE):
        return 0
    try:
        opts, words = _edit_args(args)
    except ValueError as e:
        say("%s edit -- %s needs a value" % (MARK, e))
        return 2
    at = opts["at"]
    if at is not None:
        try:
            at = max(0, int(at))
        except ValueError:
            say("%s edit -- --at N is a byte offset" % MARK)
            return 2
    if at is None and not words and not opts["decline"]:
        say(EDIT_USAGE.rstrip())
        return 2
    data = "" if sys.stdin.isatty() else sys.stdin.read()
    if not data:
        die("edit reads stdin -- spark edit --type FT words < FILE")
    if opts["decline"]:
        # the pane's d key: the note on stdin retires for this file name
        try:
            ledger.decline(opts["name"], data, config.load())
        except ledger.Refused as e:
            say("%s edit --decline -- %s" % (MARK, e.hint))
            return 2
        except OSError as e:
            die("the ledger could not be written: %s" % e)
        return 0
    sel = None
    if opts["sel"] is not None:
        try:
            sel = (int(opts["sel"][0]), int(opts["sel"][1]))
        except ValueError:
            sel = (-1, -1)
        if not 0 <= sel[0] <= sel[1] <= len(data):
            say("%s edit -- --sel A B are byte offsets, 0 <= A <= B <= %d" % (MARK, len(data)))
            return 2
    tid = opts["thread"].strip()
    if tid and not forge.valid_id(tid):
        say("%s edit -- --thread ID is [A-Za-z0-9_-]" % MARK)
        return 2
    ftype = opts["type"].strip() if opts["type"].strip() != "unknown" else ""
    label = _edit_label(os.path.basename(opts["name"].strip()), ftype, opts["part"])
    about = opts["about"].strip()
    head = "The author says: %s\n" % about if about else ""
    cfg = config.load()
    if at is not None:
        kind, role, max_tokens = "complete", "spark", 160
        text = "Continue at the cursor."
        before, after = data[max(0, at - EDIT_BEFORE):at], data[at:at + EDIT_AFTER]
        context = head + label + "\nBefore the cursor:\n" + before
        if after:
            context += "\n\nAfter the cursor:\n" + after
    elif words[0] == "?":
        kind, role, max_tokens = "ask", "ember", 600
        text = " ".join(words[1:]).strip() or persona.REVIEW
        # a thread: the same id again continues it -- the words alone when
        # the text is the one the first turn carried, else the text again
        tid = forge.open_thread(cfg, tid) if tid else None
        history = forge.history(tid) if tid else []
        sha = _sha(data)
        if history:
            first = next((m for m in forge.load(tid) if m.get("role") == "user"), {})
            context = "" if first.get("text_sha") == sha else head + label.replace(":", ", as it is now:") + "\n" + forge.clip(data)
        elif sel:
            start = max(0, sel[0] - 200)
            reading, tail = _edit_reading(cfg, data[start:start + EDIT_READ])
            context = (head + reading + ledger.block(cfg, opts["name"], data) + label[:-1]
                       + " -- the question is about the part between the marks:\n"
                       + _edit_window(data, sel[0], sel[1]) + tail)
        else:
            reading, tail = _edit_reading(cfg, data)
            context = head + reading + ledger.block(cfg, opts["name"], data) + label + "\n" + forge.clip(data) + tail
    else:
        kind, role = "rewrite", "ember"
        if len(data) > EDIT_MAX:
            die("the text is %d chars; a rewrite takes at most %d -- select less" % (len(data), EDIT_MAX))
        max_tokens = min(6000, len(data) // 2 + 200)
        text = " ".join(words).strip()
        context = head + label + "\n" + data
    from . import text as textmod
    # a rewrite keeps the text's own final-newline shape: the editor splices
    # the reply over the selection, and a model that drops or adds the last
    # newline would join or split lines
    # an answer's quotes are checked against the text, line by line, and
    # the ones the text does not hold are marked where they stand
    anchors = textmod.Anchors(sys.stdout, data) if kind == "ask" else None
    fence = textmod.Fence(anchors or sys.stdout, newline=data.endswith("\n") if kind == "rewrite" else None)

    def done():
        fence.close()
        if anchors:
            anchors.close()
    try:
        s = session.Session(cfg, "edit-" + kind, _shell_default(), "", role=role,
                            history=history if kind == "ask" else None)
        out, ms = s.ask_stream(text, context, fence.feed, max_tokens=max_tokens, timeout=EDIT_TIMEOUT)
    except wire.BrainError as e:
        done()
        die(e.hint)
    except KeyboardInterrupt:
        done()
        raise
    done()
    counts = {"quotes": anchors.quoted, "unanchored": anchors.missed} if anchors else {}
    if kind == "ask" and tid:
        forge.append(cfg, tid, "user", persona.user_message(text, "", context), text_sha=sha)
        forge.append(cfg, tid, "assistant", out or "")
        counts["thread"] = tid
    s.record(kind=kind, chars=len(data), ms=ms, **counts)
    return 0


# ------------------------------------------------------------ last/status
def _fmt_turn(t):
    # a turn is numbers only (session.TEXT_FIELDS); the words come from
    # the sealed thread it names, when this machine can open it
    if not t:
        return "(no turns yet)"
    line = body = ""
    if t.get("thread"):
        msgs = forge.load(t["thread"])
        asked = [m for m in msgs if m.get("role") == "user"]
        replied = [m for m in msgs if m.get("role") == "assistant"]
        line = asked[-1]["text"] if asked else ""
        body = replied[-1]["text"] if replied else ""
    head = "%s  %s  %s" % (t.get("ts", "?"), t.get("kind", "?"), line)
    mark = glyph("warn") if t.get("kind") == "danger" else glyph("hammer")
    body = "  %s %s" % (mark, body) if body else "  (the thread is gone -- numbers only)"
    tail = "  via %s (%s) %s" % (t.get("backend", "?"), t.get("model", "?"), speed(t))
    if t.get("thread"):
        tail += "  thread %s" % t["thread"]
    return "\n".join([head, body, tail])


def speed(t):
    """'12.3 tok/s (prompt 96 tok/s, 1.1 s)' for a turn, or just the time"""
    ms = t.get("ms")
    secs = "%.1f s" % (ms / 1000.0) if isinstance(ms, (int, float)) else "?"
    if t.get("tg_tps"):
        return "%.1f tok/s (prompt %.0f tok/s, %s)" % (t["tg_tps"], t.get("pp_tps") or 0, secs)
    return secs


def cmd_last(args):
    if _help(args, LAST_USAGE):
        return 0
    say(_fmt_turn(session.last_turn()))
    return 0


def _role_rows(cfg, url, is_forge):
    """[(role, stem, loaded)] when the brain serves both roles (spark
    first), [] for one model -- the callers then say nothing extra."""
    try:
        rows = wire.models(cfg, url, forge=is_forge)
    except wire.BrainError:
        return []
    if len(rows) < 2:
        return []
    order = {"spark": 0, "ember": 1}
    return sorted(rows, key=lambda r: (order.get(r[0], 2), r[0]))


def cmd_brain(args):
    if _help(args, BRAIN_USAGE):
        return 0
    porcelain = "--porcelain" in args
    cfg = config.load()
    try:
        url, model, is_forge = wire.resolve_brain(cfg, fresh="--fresh" in args)
    except wire.BrainError as e:
        if not porcelain:
            say(glyph("hammer") + " " + e.hint)
        return 1
    if porcelain:                       # contract 5: the spark role's stem
        say("%s\t%s\t%s" % (url, model, "forge" if is_forge else "model"))
        return 0
    say("%s  %s  (%s)" % (url, model, "a FORGE" if is_forge else "a llama-server"))
    for role, stem, loaded in _role_rows(cfg, url, is_forge):
        say("  %s  %s  %s" % (role, stem, "loaded" if loaded else "unloaded"))
    return 0


def live_widgets():
    """[(shell, pid)] of shells that sourced the widget and are still alive"""
    out = []
    try:
        for name in os.listdir(WIDGETS_DIR):
            try:
                with open(os.path.join(WIDGETS_DIR, name), encoding="utf-8") as f:
                    shell, pid, _ = (f.read().split() + ["", "", ""])[:3]
                os.kill(int(pid), 0)
                out.append((shell, int(pid)))
            except (OSError, ValueError):
                try:
                    os.remove(os.path.join(WIDGETS_DIR, name))
                except OSError:
                    pass
    except OSError:
        pass
    return out


def cmd_status(args, _bare=False):
    if _help(args, STATUS_USAGE):
        return 0
    # a clone with no site.env yet, at a terminal: the offer, not a status
    from . import SITE_ENV
    if not os.path.exists(SITE_ENV) and sys.stdout.isatty():
        from . import setup
        cmd_ver([])
        say(setup.SIGN)
        return 0
    cfg = config.load()
    if _bare and cfg.quiet_start:
        # SITE_QUIET_START=yes: bare spark is one line; spark status stays full
        try:
            url, model, is_forge = wire.resolve_brain(cfg)
            # only a machine that really serves an ember role says "ember";
            # a single model is just the model
            ember = next((s for role, s, _l in _role_rows(cfg, url, is_forge) if role == "ember"), None)
            what = ("ember %s" % ember) if ember else ("model %s" % model)
            say("%s -- %s at %s (spark status for the rest)" % (MARK, what, url))
        except wire.BrainError as e:
            say("%s -- %s (spark status for the rest)" % (MARK, e.hint))
        return 0
    say("%s -- %s's AI on %s" % (MARK, cfg.user, cfg.name))
    t0 = time.time()
    try:
        url, model, is_forge = wire.resolve_brain(cfg, fresh=True)
        rows = _role_rows(cfg, url, is_forge)
        if rows:
            model = " - ".join("%s %s" % (role, stem) for role, stem, _loaded in rows)
        say("  brain    %s  (%s%s, /health %dms)" % (url, model, ", a FORGE" if is_forge else "", int((time.time() - t0) * 1000)))
    except wire.BrainError as e:
        say("  brain    " + e.hint)
    w = live_widgets()
    say("  widget   %s%s" % ("off (spark on)" if os.path.exists(OFF_FLAG) else "on",
                              "  in %s" % ", ".join("%s %d" % x for x in w) if w else "  (no shell has sourced it)"))
    st = engine.service_state(cfg)
    say("  service  %s" % {"loaded": "always-on", "disabled": "disabled on purpose", "absent": "on demand (spark serve)"}[st])
    from . import SOUL_FILE, memory, soul
    _, source = soul.read(cfg)
    if source == "file":
        say("  soul     yours, %d chars (%s)" % (len(soul.text(cfg)), _short(SOUL_FILE)))
    elif source == "env":
        say("  soul     from SPARK_PERSONA_EXTRA (spark soul edit)")
    else:
        say("  soul     built-in (spark soul edit)")
    nf = len(memory.facts(cfg))
    say("  memory   %s" % ("%d fact%s" % (nf, "" if nf == 1 else "s") if cfg.memory else "off"))
    n = len(forge.list_threads(10**6))
    say("  history  %s" % ("off" if cfg.history <= 0 else "%d days, %s, %d thread%s"
                           % (cfg.history, _short(os.path.join(STATE_DIR, "turns")), n, "" if n == 1 else "s")))
    say("  last     " + _fmt_turn(session.last_turn()).replace("\n", "\n           "))
    return 0


def _short(path):
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path.startswith(home + "/") else path


def cmd_off(args):
    if _help(args, OFF_USAGE):
        return 0
    state_dir()
    open(OFF_FLAG, "a").close()
    say("%s off -- Enter is the shell's again (Esc s and spark <words> still work) -- spark on restores" % MARK)
    from . import check
    check.refresh()
    return 0


def cmd_on(args):
    if _help(args, ON_USAGE):
        return 0
    try:
        os.remove(OFF_FLAG)
    except OSError:
        pass
    say("%s on -- ? words and words? go to the model again" % MARK)
    from . import check
    check.refresh()
    return 0


def cmd_history(args):
    if _help(args, HISTORY_USAGE):
        return 0
    if args[:1] == ["clear"]:
        n = session.clear()
        m = forge.clear()
        say("%s history: removed %d day file%s and %d thread%s" % (MARK, n, "" if n == 1 else "s", m, "" if m == 1 else "s"))
        return 0
    return paged(_history_show)


def _history_show():
    cfg = config.load()
    say("%s history: %s" % (MARK, "off" if cfg.history <= 0 else "%d days under %s" % (cfg.history, _short(STATE_DIR))))
    say("  spark history clear   removes every turn and thread kept so far")
    threads = forge.list_threads(5)
    if threads:
        say("  threads (?? words goes on with the newest):")
        for th in threads:
            say("  %s  %d turn%s  %s" % (th["id"], th["turns"], "" if th["turns"] == 1 else "s", th["title"]))
    return 0


_ORIGIN_RE = re.compile(r"github\.com[:/]([^/]+)/(.+?)(?:\.git)?/?$")


def credits():
    """`by <org> <sep> github.com/<org>/<repo>`, derived from this clone's
    `origin` remote so a fork shows its own name; the literal fallback
    (2 s timeout, never blocks) when there is no remote to read."""
    from . import run
    rc, out = run(["git", "-C", REPO, "remote", "get-url", "origin"], timeout=2)
    m = _ORIGIN_RE.search(out.strip()) if rc == 0 else None
    org, repo = m.groups() if m else ("forgewright-ai", "spark")
    return "by %s%sgithub.com/%s/%s" % (org, glyph("sep"), org, repo)


def _llama_version():
    """LLAMA_VERSION out of bootstrap.sh -- one file read, no network: the
    login greeting (spark ver) must stay fast."""
    try:
        with open(os.path.join(REPO, "bootstrap.sh"), encoding="utf-8") as f:
            m = re.search(r"^LLAMA_VERSION=(\S+)", f.read(), re.M)
        return m.group(1) if m else "?"
    except OSError:
        return "?"


def cmd_ver(args):
    """logo, version, credits"""
    if _help(args, VER_USAGE):
        return 0
    for path in (os.path.join(CONFIG_DIR, "banner"), os.path.join(REPO, "home", ".config", "spark", "banner")):
        try:
            with open(path, encoding="utf-8") as f:
                logo = f.read()
            break
        except OSError:
            logo = ""
    say()
    if logo:
        logo = logo.replace("\\033", "\033") if sys.stdout.isatty() else re.sub(r"\\033\[[0-9;]*m", "", logo)
        say(logo.rstrip("\n"))
        say()
    # this line is the login greeting, so the version is the cached one
    # (lib/spark/version.py): no blocking git call on the common path.
    say("%s %s" % (MARK, version.version()))
    say(credits())
    say("engine llama.cpp %s (MIT) -- CREDITS.md names the rest" % _llama_version())
    return 0


# ---------------------------------------------------- soul and memory
# Imported when called: `spark line` (every Enter) must start light.
def cmd_soul(args):
    from . import soul
    return soul.cmd_soul(args)


def cmd_remember(args):
    from . import memory
    return memory.cmd_remember(args)


def cmd_forget(args):
    from . import memory
    return memory.cmd_forget(args)


def cmd_memory(args):
    from . import memory
    return memory.cmd_memory(args)


def cmd_chat(args):
    return forge.cmd_chat(args)


def cmd_talk(args):
    # removed in v1.3: one line naming the new verb, no forwarding
    say("%s talk -- gone: spark chat" % MARK)
    return 2


def cmd_do(args):
    from . import do
    return do.cmd_do(args)


# --------------------------------------------------------------- dispatch
COMMANDS = {
    "line": cmd_line, "last": cmd_last, "status": cmd_status, "brain": cmd_brain,
    "explain": cmd_explain, "edit": cmd_edit, "off": cmd_off, "on": cmd_on, "history": cmd_history,
    "soul": cmd_soul, "remember": cmd_remember, "forget": cmd_forget, "memory": cmd_memory, "ledger": ledger.cmd_ledger,
    "chat": cmd_chat, "talk": cmd_talk, "do": cmd_do,
    "ver": cmd_ver, "version": cmd_ver, "--version": cmd_ver,
}


def main(argv):
    if not argv:
        return cmd_status([], _bare=True)
    head, rest = argv[0], argv[1:]
    return COMMANDS.get(head, lambda _r: cmd_ask(argv))(rest)
