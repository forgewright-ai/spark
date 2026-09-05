# spark.cli -- the client subcommands: line (what the widgets call), ask,
# explain, last, brain, status, off, on, history, and the thin dispatch to
# soul / remember / forget / memory / chat / do (imported only when called).

import os
import re
import sys
import time

from . import CONFIG_DIR, MARK, OFF_FLAG, REPO, STATE_DIR, WIDGETS_DIR, config, die, glyph, paged, say, state_dir
from . import engine, forge, persona, session, version, wire

HINT_COLS = 80
STDIN_TAIL = 6000          # what `explain` sends at most: the last 6 kB

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

  spark off                   Enter is the shell's again; Esc a and
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


# ------------------------------------------------------------ last/status
def _fmt_turn(t):
    if not t:
        return "(no turns yet)"
    head = "%s  %s  %s" % (t.get("ts", "?"), t.get("kind", "?"), t.get("line", ""))
    if t.get("command"):
        body = "  %s %s\n  %s" % (glyph("warn") if t.get("kind") == "danger" else glyph("hammer"), t["command"], t.get("hint", ""))
    else:
        body = "  " + (t.get("answer") or "")
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
    say("%s off -- Enter is the shell's again (Esc a and spark <words> still work) -- spark on restores" % MARK)
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
    "explain": cmd_explain, "off": cmd_off, "on": cmd_on, "history": cmd_history,
    "soul": cmd_soul, "remember": cmd_remember, "forget": cmd_forget, "memory": cmd_memory,
    "chat": cmd_chat, "talk": cmd_talk, "do": cmd_do,
    "ver": cmd_ver, "version": cmd_ver, "--version": cmd_ver,
}


def main(argv):
    if not argv:
        return cmd_status([], _bare=True)
    head, rest = argv[0], argv[1:]
    return COMMANDS.get(head, lambda _r: cmd_ask(argv))(rest)
