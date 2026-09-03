# spark.forge -- the identity a request carries, and the threads it may
# continue. The identity is the soul (who spark is) plus the remembered
# facts; it changes only when the user edits one of them, so the system
# message stays byte-stable and llama-server's prompt cache keeps hitting.
#
# A thread is one conversation: ~/.local/state/spark/threads/<id>.jsonl
# (dir 0700, files 0600), one message per line {"ts","role","text",...}.
# `? words` and `spark <words>` start one; `?? words` and `spark chat`
# continue the newest. SPARK_HISTORY=off keeps no threads at all, so `??`
# behaves like `?`.
#
# reply() is one turn of the FORGE without a terminal: the prompt, the
# REPL and (later) the page all go through it. `@FILE` words name files
# whose text rides along in the request's context slot.

import json
import os
import re
import sys
import time

from . import THREADS_DIR, log_exc, state_dir
from . import memory, persona, soul

HISTORY_MAX_CHARS = 20000     # what a continued thread sends at most; oldest pairs go first
FILE_HEAD, FILE_TAIL = 4000, 12000
FILE_MAX = FILE_HEAD + FILE_TAIL  # what an @FILE sends at most: its head, a cut mark, its tail
SUMMARISE = "Summarise this file."  # the question when @FILE comes alone
TITLE_COLS = 60
_ID = re.compile(r"^[A-Za-z0-9_-]+$")


class RefError(Exception):
    """An @FILE that cannot be sent; hint is the one line for a human."""

    def __init__(self, hint):
        super().__init__(hint)
        self.hint = hint


# --------------------------------------------------------------- identity
def identity(cfg):
    """The soul, then the remembered facts when there are any."""
    t = soul.text(cfg)
    m = memory.block(cfg)
    return t + ("\n\n" + m if m else "")


def system(cfg, mode, shell):
    """The whole system message: machine facts, identity, the mode's task.
    Byte-stable per machine, shell and mode until the soul or memory
    changes. A conversation (chat) gets one machine line, not the shell
    brief -- see persona.mode_prefix."""
    return persona.mode_prefix(cfg, mode, shell) + "\n\n" + identity(cfg) + "\n\n" + persona.MODES[mode]


# ---------------------------------------------------------------- threads
def _dir():
    state_dir()
    os.makedirs(THREADS_DIR, exist_ok=True)
    try:
        os.chmod(THREADS_DIR, 0o700)
    except OSError:
        pass
    return THREADS_DIR


def valid_id(tid):
    return bool(tid) and isinstance(tid, str) and bool(_ID.match(tid))


def _path(tid):
    if not valid_id(tid):
        raise ValueError("bad thread id: %r" % (tid,))
    return os.path.join(THREADS_DIR, tid + ".jsonl")


def exists(tid):
    """Whether a thread file is there (valid id only)."""
    return valid_id(tid) and os.path.isfile(_path(tid))


def new_thread(cfg):
    """A fresh id, its (empty) file created now so two threads born in the
    same second get -2, -3. None when SPARK_HISTORY is off."""
    if cfg.history <= 0:
        return None
    base = time.strftime("%Y-%m-%d-%H%M%S")
    try:
        d = _dir()
        for n in range(1, 100):
            tid = base if n == 1 else "%s-%d" % (base, n)
            try:
                fd = os.open(os.path.join(d, tid + ".jsonl"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.close(fd)
                return tid
            except FileExistsError:
                continue
    except OSError:
        log_exc("new thread")
    return None


def _files():
    """[(mtime_ns, id)] of every thread file, unsorted."""
    out = []
    try:
        for name in os.listdir(THREADS_DIR):
            if name.endswith(".jsonl") and _ID.match(name[:-6]):
                try:
                    out.append((os.stat(os.path.join(THREADS_DIR, name)).st_mtime_ns, name[:-6]))
                except OSError:
                    pass
    except OSError:
        pass
    return out


def last_thread():
    """The id of the thread touched last, or None."""
    fs = _files()
    return max(fs)[1] if fs else None


def load(tid):
    """Every message of a thread, as written: [{"ts","role","text",...}]."""
    out = []
    try:
        with open(_path(tid), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict) and d.get("role") and isinstance(d.get("text"), str):
                    out.append(d)
    except OSError:
        pass
    return out


def append(cfg, tid, role, text, **fields):
    """One message onto a thread (0600). Nothing when history is off."""
    if cfg.history <= 0 or not tid:
        return
    d = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "role": role, "text": text}
    d.update(fields)
    try:
        _dir()
        fd = os.open(_path(tid), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    except OSError:
        log_exc("append thread")


def history(tid):
    """The thread as chat messages [{"role","content"}], the oldest pairs
    dropped until at most HISTORY_MAX_CHARS remain. [] for no thread."""
    if not tid:
        return []
    msgs = [{"role": m["role"], "content": m["text"]} for m in load(tid) if m["role"] in ("user", "assistant")]
    total = sum(len(m["content"]) for m in msgs)
    while msgs and total > HISTORY_MAX_CHARS:
        total -= len(msgs.pop(0)["content"])
        if msgs and msgs[0]["role"] == "assistant":
            total -= len(msgs.pop(0)["content"])
    return msgs


def pick(cfg, more):
    """(thread id, history) for a turn: the newest thread continued when
    `more` asks for it, else a new one. (None, []) when history is off."""
    if cfg.history <= 0:
        return None, []
    if more:
        tid = last_thread()
        if tid:
            return tid, history(tid)
    return new_thread(cfg), []


def _title(s):
    s = " ".join((s or "").split())
    return s if len(s) <= TITLE_COLS else s[:TITLE_COLS - 3] + "..."


def list_threads(n=5):
    """The newest n threads that hold a turn: [{"id","ts","title","turns"}]."""
    out = []
    for _, tid in sorted(_files(), reverse=True):
        msgs = load(tid)
        users = [m for m in msgs if m["role"] == "user"]
        if not users:
            continue
        out.append({"id": tid, "ts": users[0].get("ts", ""), "title": _title(users[0]["text"]), "turns": len(users)})
        if len(out) >= n:
            break
    return out


def clear():
    """Remove every thread; how many."""
    n = 0
    try:
        for name in os.listdir(THREADS_DIR):
            if name.endswith(".jsonl"):
                os.remove(os.path.join(THREADS_DIR, name))
                n += 1
    except OSError:
        pass
    return n


def prune(cfg):
    """Delete threads untouched for more than SPARK_HISTORY days."""
    try:
        cutoff = time.time() - cfg.history * 86400
        for name in os.listdir(THREADS_DIR):
            p = os.path.join(THREADS_DIR, name)
            if name.endswith(".jsonl") and os.path.getmtime(p) < cutoff:
                os.remove(p)
    except OSError:
        pass


# ------------------------------------------------------------------ @FILE
def refs(words):
    """(the words that are not @FILE references, the file names as typed)."""
    kept, paths = [], []
    for w in words:
        if w.startswith("@") and len(w) > 1:
            paths.append(w[1:])
        else:
            kept.append(w)
    return kept, paths


def read_file(name, cwd=""):
    """The text of one @FILE, relative to cwd (~ expanded): at most FILE_MAX
    chars, the middle cut. Refuses a directory, a missing file, a binary."""
    path = os.path.expanduser(name)
    if not os.path.isabs(path) and cwd:
        path = os.path.join(cwd, path)
    if os.path.isdir(path):
        raise RefError("@%s is a directory -- name a file" % name)
    try:
        with open(path, "rb") as f:
            head = f.read(8192)
            if b"\0" in head:
                raise RefError("@%s is not a text file" % name)
            data = (head + f.read()).decode("utf-8", errors="replace")
    except FileNotFoundError:
        raise RefError("@%s: no such file" % name)
    except OSError as e:
        raise RefError("@%s: %s" % (name, e.strerror or e))
    if len(data) > FILE_MAX:
        data = data[:FILE_HEAD] + "\n[... %d chars cut ...]\n" % (len(data) - FILE_MAX) + data[-FILE_TAIL:]
    return data


def file_context(paths, cwd=""):
    """The context blocks for @FILEs: `File NAME:` (the name as typed, never
    the absolute path) and the text, blank-line separated."""
    return "\n\n".join("File %s:\n%s" % (p, read_file(p, cwd)) for p in paths)


def read_refs(words, cwd=""):
    """(words without the @FILE references, their context) -- RefError when
    one cannot be sent."""
    kept, paths = refs(words)
    return kept, file_context(paths, cwd)


# ------------------------------------------------------------------ reply
def reply(cfg, thread, text, files=(), cwd="", shell="", mode="chat", on_delta=None, context="", line=None, brain=None):
    """One turn, no terminal: the answer streams through on_delta(text).
    `thread` None starts one (None stays None when history is off);
    `files` are @FILE names as typed, read here relative to cwd and sent
    after `context` (piped output). Both messages land on the thread and
    the turn is recorded. `brain` goes to the Session (the FORGE's own
    upstream). Returns (thread, answer, ms). Raises RefError before any
    request, wire.BrainError from the request. A KeyboardInterrupt during
    the request appends the user line and, when any text arrived, the
    partial reply (partial=True); the thread id rides on the exception
    (`e.thread`) so the caller can keep going with it. Nothing is printed
    here -- that is the caller's job."""
    from . import session          # session imports forge: resolved late on purpose
    context = "\n\n".join(c for c in (context, file_context(files, cwd)) if c)
    if not text and files:
        text = SUMMARISE
    if line is None:
        line = " ".join(["@" + f for f in files] + ([text] if text else []))
    if thread is None:
        thread = new_thread(cfg)
    s = session.Session(cfg, mode, shell, cwd, history(thread) if thread else None, brain)
    tap = on_delta or (lambda d: None)
    collected = []

    def on_delta_tap(d):
        collected.append(d)
        tap(d)

    try:
        answer, ms = s.ask_stream(text, context, on_delta_tap)
    except KeyboardInterrupt as e:
        append(cfg, thread, "user", line, mode=mode, cwd=cwd)
        partial = "".join(collected)
        if partial:
            append(cfg, thread, "assistant", partial, kind="answer", partial=True)
        e.thread = thread
        raise
    s.record(kind="answer", line=line, answer=answer, ms=ms, thread=thread)
    append(cfg, thread, "user", line, mode=mode, cwd=cwd)
    append(cfg, thread, "assistant", answer, kind="answer")
    return thread, answer, ms


# ------------------------------------------------------------------- chat
CHAT_USAGE = """%s chat -- a conversation

  spark chat <words>   one more turn on the newest thread, streamed
  spark chat           a conversation at the `chat> ` prompt

  Inside it: @FILE words asks about a file; /help lists the verbs (/new,
  /last, /model); /q (or /quit, /exit, :q, quit, exit, bye, Ctrl-D) ends,
  silently; Ctrl-C cancels a reply in progress without ending the chat.
  Every turn is kept as a thread (spark history).
"""

# Any of these alone ends the conversation, silently. Generous on purpose:
# a quit word the REPL does not know goes to the model, which role-plays
# an exit while the prompt lives on -- a first-session trap.
QUIT_WORDS = ("/q", "/quit", "/exit", ":q", ":quit", ":wq", "quit", "exit", "bye")


def _slash_help(cfg, thread):
    from . import say
    say("/help   this list")
    say("/new    a fresh thread")
    say("/last   the last turn, with its tok/s")
    say("/model  which model is answering")
    say("/q      end the conversation (Ctrl-D works too)")
    return thread


def _slash_new(cfg, thread):
    from . import MARK, say
    say("%s: a fresh thread" % MARK)
    return None


def _slash_last(cfg, thread):
    from . import cli, say, session
    say(cli._fmt_turn(session.last_turn()))
    return thread


def _slash_model(cfg, thread):
    from . import cli, say, wire
    try:
        url, model, is_forge = wire.resolve_brain(cfg)
    except wire.BrainError as e:
        print("spark: " + e.hint, file=sys.stderr, flush=True)
        return thread
    stem = model
    for role, s, _loaded in cli._role_rows(cfg, url, is_forge):
        if role == "ember":
            stem = s
            break
    say("ember: %s via %s" % (stem, url))
    return thread


# /q is not here: QUIT_WORDS is checked first, so it never reaches this dict.
SLASH_VERBS = {"/help": _slash_help, "/new": _slash_new, "/last": _slash_last, "/model": _slash_model}


def cmd_chat(args):
    from . import CHAT_HISTORY_FILE, MARK, glyph, config, say, state_dir, wire
    from . import cli
    if args and args[0] in ("-h", "--help", "help"):
        say(CHAT_USAGE.rstrip() % MARK)
        return 0
    cfg = config.load()
    thread = last_thread() if cfg.history > 0 else None    # `more`: go on with the newest
    if args:
        words, paths = refs(args)
        return cli._stream("chat", " ".join(words), paths, thread=thread)
    tty = sys.stdin.isatty()
    hist_on = tty and cfg.history > 0
    readline = None
    if tty:
        try:
            import readline as _readline
            readline = _readline
        except ImportError:
            readline = None
        if readline and hist_on:
            readline.set_history_length(500)
            try:
                readline.read_history_file(CHAT_HISTORY_FILE)
            except OSError:
                pass
    say("chat -- /help, Ctrl-D or /q ends")
    try:
        while True:
            try:
                if sys.stdin.isatty():
                    try:
                        import termios
                        termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
                    except Exception:
                        pass    # scrolled-in escape codes must not become input
                text = input("chat> ")
            except EOFError:
                if tty:
                    say()
                break
            except KeyboardInterrupt:
                if tty:
                    say()
                break
            text = text.strip()
            if not text:
                continue
            if text in QUIT_WORDS:
                break
            if text.startswith("/"):
                verb = text.split()[0]
                fn = SLASH_VERBS.get(verb)
                if fn:
                    thread = fn(cfg, thread)
                else:
                    print("spark: no %s -- /help lists them" % verb, file=sys.stderr, flush=True)
                say()          # a blank line between turns
                continue
            words, paths = refs(text.split())
            try:
                thread = cli.stream_turn(cfg, "chat", " ".join(words), paths, thread=thread)
            except (RefError, wire.BrainError) as e:
                print("spark: " + e.hint, file=sys.stderr, flush=True)
            except KeyboardInterrupt as e:
                thread = getattr(e, "thread", thread)
                say()
                say("%s (stopped)" % glyph("hammer"))
            say()              # a blank line between turns
    finally:
        if readline and hist_on:
            state_dir()
            try:
                readline.write_history_file(CHAT_HISTORY_FILE)
                os.chmod(CHAT_HISTORY_FILE, 0o600)
            except OSError:
                pass
    return 0


cmd_talk = cmd_chat    # the old name dispatches identically for one version
