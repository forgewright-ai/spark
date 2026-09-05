# spark.forge -- the identity a request carries, and the threads it may
# continue. The identity is the soul (who spark is) plus the remembered
# facts; it changes only when the user edits one of them, so the system
# message stays byte-stable and llama-server's prompt cache keeps hitting.
#
# A thread is one conversation, sealed: one file per thread under the
# owning user's store, ~/.local/state/spark/users/<name>/threads/
# <id>.sealed (dir 0700, files 0600) -- the vault format, one encrypted
# {"ts","role","text",...} record per line. The module-level functions
# below work on this machine's own account (auto-minted on first use);
# a Store works on any user's. `? words` and `spark <words>` start a
# thread; `?? words` and `spark chat` continue the newest.
# SPARK_HISTORY=off keeps no threads at all, so `??` behaves like `?`.
#
# reply() is one turn of the FORGE without a terminal: the prompt, the
# REPL and the page all go through it. `@FILE` words name files whose
# text rides along in the request's context slot.

import json
import os
import re
import sys
import time

from . import THREADS_DIR, log_exc, state_dir, vault
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
def identity(cfg, mem=None):
    """The soul, then the remembered facts when there are any. `mem`
    names whose facts (a memory.store_of tuple): the FORGE passes the
    requesting user's; None is this machine's own account."""
    t = soul.text(cfg)
    m = memory.block(cfg, mem)
    return t + ("\n\n" + m if m else "")


def system(cfg, mode, shell, mem=None):
    """The whole system message: machine facts, identity, the mode's task.
    Byte-stable per machine, shell and mode until the soul or memory
    changes. A conversation (chat) gets one machine line, not the shell
    brief -- see persona.mode_prefix."""
    return persona.mode_prefix(cfg, mode, shell) + "\n\n" + identity(cfg, mem) + "\n\n" + persona.MODES[mode]


# ---------------------------------------------------------------- threads
def valid_id(tid):
    return bool(tid) and isinstance(tid, str) and bool(_ID.match(tid))


def _title(s):
    s = " ".join((s or "").split())
    return s if len(s) <= TITLE_COLS else s[:TITLE_COLS - 3] + "..."


class Store:
    """One user's sealed thread store: the directory and the data key.
    Every read decrypts, every write seals; a caller without the key has
    no store. The module-level functions below are this machine's own."""

    def __init__(self, tdir, dk, name=""):
        self.tdir, self.dk, self.name = tdir, dk, name

    def _dir(self):
        if self.name:
            from . import users
            users.make_dirs(self.name)
            return self.tdir
        state_dir()
        os.makedirs(self.tdir, mode=0o700, exist_ok=True)
        try:
            os.chmod(self.tdir, 0o700)
        except OSError:
            pass
        return self.tdir

    def _path(self, tid):
        if not valid_id(tid):
            raise ValueError("bad thread id: %r" % (tid,))
        return os.path.join(self.tdir, tid + ".sealed")

    def exists(self, tid):
        return valid_id(tid) and os.path.isfile(self._path(tid))

    def new_thread(self, cfg):
        """A fresh id, its file (header only) created now so two threads
        born in the same second get -2, -3. None when history is off."""
        if cfg.history <= 0:
            return None
        base = time.strftime("%Y-%m-%d-%H%M%S")
        try:
            d = self._dir()
            for n in range(1, 100):
                tid = base if n == 1 else "%s-%d" % (base, n)
                try:
                    fd = os.open(os.path.join(d, tid + ".sealed"),
                                 os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(fd, "w") as f:
                        f.write(vault.header("thread", tid) + "\n")
                    return tid
                except FileExistsError:
                    continue
        except OSError:
            log_exc("new thread")
        return None

    def _files(self):
        """[(mtime_ns, id)] of every thread file, unsorted."""
        out = []
        try:
            for name in os.listdir(self.tdir):
                if name.endswith(".sealed") and _ID.match(name[:-7]):
                    try:
                        out.append((os.stat(os.path.join(self.tdir, name)).st_mtime_ns, name[:-7]))
                    except OSError:
                        pass
        except OSError:
            pass
        return out

    def last_thread(self):
        fs = self._files()
        return max(fs)[1] if fs else None

    def load(self, tid):
        """Every message of a thread: [{"ts","role","text",...}]. A record
        that does not open (or parse) is dropped, never fatal."""
        out = []
        try:
            for rec in vault.read_sealed(self._path(tid), self.dk):
                try:
                    d = json.loads(rec.decode("utf-8"))
                except ValueError:
                    continue
                if isinstance(d, dict) and d.get("role") and isinstance(d.get("text"), str):
                    out.append(d)
        except (OSError, vault.SealError):
            pass
        return out

    def append(self, cfg, tid, role, text, **fields):
        """One sealed message onto a thread. Nothing when history is off."""
        if cfg.history <= 0 or not tid:
            return
        d = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "role": role, "text": text}
        d.update(fields)
        try:
            self._dir()
            vault.append_sealed(self._path(tid), self.dk, "thread", tid,
                                json.dumps(d, ensure_ascii=False).encode("utf-8"))
        except (OSError, vault.SealError):
            log_exc("append thread")

    def history(self, tid):
        """The thread as chat messages [{"role","content"}], the oldest
        pairs dropped until at most HISTORY_MAX_CHARS remain."""
        if not tid:
            return []
        msgs = [{"role": m["role"], "content": m["text"]}
                for m in self.load(tid) if m["role"] in ("user", "assistant")]
        total = sum(len(m["content"]) for m in msgs)
        while msgs and total > HISTORY_MAX_CHARS:
            total -= len(msgs.pop(0)["content"])
            if msgs and msgs[0]["role"] == "assistant":
                total -= len(msgs.pop(0)["content"])
        return msgs

    def pick(self, cfg, more):
        if cfg.history <= 0:
            return None, []
        if more:
            tid = self.last_thread()
            if tid:
                return tid, self.history(tid)
        return self.new_thread(cfg), []

    def list_threads(self, n=5):
        """The newest n threads that hold a turn: [{"id","ts","title","turns"}]."""
        out = []
        for _, tid in sorted(self._files(), reverse=True):
            msgs = self.load(tid)
            users = [m for m in msgs if m["role"] == "user"]
            if not users:
                continue
            out.append({"id": tid, "ts": users[0].get("ts", ""),
                        "title": _title(users[0]["text"]), "turns": len(users)})
            if len(out) >= n:
                break
        return out

    def clear(self):
        """Remove every thread; how many."""
        n = 0
        try:
            for name in os.listdir(self.tdir):
                if name.endswith(".sealed"):
                    os.remove(os.path.join(self.tdir, name))
                    n += 1
        except OSError:
            pass
        return n

    def prune(self, cfg):
        """Delete threads untouched for more than SPARK_HISTORY days."""
        try:
            cutoff = time.time() - cfg.history * 86400
            for name in os.listdir(self.tdir):
                p = os.path.join(self.tdir, name)
                if name.endswith(".sealed") and os.path.getmtime(p) < cutoff:
                    os.remove(p)
        except OSError:
            pass


class _NullStore:
    """No account and none mintable: reads answer empty, writes vanish
    (logged). The line path must never crash on store trouble."""

    def exists(self, tid):
        return False

    def new_thread(self, cfg):
        return None

    def last_thread(self):
        return None

    def load(self, tid):
        return []

    def append(self, cfg, tid, role, text, **fields):
        pass

    def history(self, tid):
        return []

    def pick(self, cfg, more):
        return None, []

    def list_threads(self, n=5):
        return []

    def clear(self):
        return 0

    def prune(self, cfg):
        pass


def store_for(name, dk):
    """The sealed store of one named user (the FORGE serves these)."""
    from . import users
    return Store(os.path.join(users.user_dir(name), "threads"), dk, name)


def _provision():
    """Mint this machine's own account, named after the OS user, and log
    in -- silently: this runs deep inside the line path. The token lands
    in the account file (login-grade custody); `spark user token --new`
    prints a fresh one to carry elsewhere."""
    from . import users
    base = users.sanitize(os.environ.get("USER") or "owner")
    name = base
    for n in range(2, 100):
        if not users.exists(name):
            break
        name = "%s-%d" % (base, n)
    token = users.add(name)
    users.write_login(name, token, users.unlock(name, token))
    return name


def local_store(provision=False):
    """This machine's own store: the logged-in account's, unlocked by the
    account-key file. With provision=True a machine with no account mints
    one (write paths); without, reads answer empty instead. Returns a
    Store, or a _NullStore when there is none to be had."""
    from . import users
    try:
        name, token = users.account()
        if name and not users.exists(name) and token:
            # a login without a store (a client, or a wiped users/): the
            # same token seals a fresh local store on first write
            if provision:
                users.write_login(name, token)      # keep the login
                d = users.user_dir(name)
                if not os.path.isdir(d):
                    users.make_dirs(name)
                    vault.write_private(os.path.join(d, "token.hash"),
                                        (vault.token_hash(token) + "\n").encode())
                    vault.write_private(os.path.join(d, "key"),
                                        vault.wrap_key(vault.new_key(), token, name).encode())
            else:
                return _NullStore()
        if not name:
            if not provision:
                return _NullStore()
            name = _provision()
        dk = users.account_key()
        if dk is None:
            _, token = users.account()
            if not token:
                return _NullStore()
            dk = users.unlock(name, token)
            users.write_login(name, token, dk)
        return store_for(name, dk)
    except Exception:
        log_exc("local store")
        return _NullStore()


def exists(tid):
    """Whether a thread file is there (valid id only)."""
    return local_store().exists(tid)


def new_thread(cfg):
    """A fresh id on this machine's own store. None when history is off."""
    if cfg.history <= 0:
        return None
    return local_store(provision=True).new_thread(cfg)


def last_thread():
    """The id of the thread touched last, or None."""
    return local_store().last_thread()


def load(tid):
    """Every message of a thread, decrypted: [{"ts","role","text",...}]."""
    return local_store().load(tid)


def append(cfg, tid, role, text, **fields):
    """One sealed message onto a thread. Nothing when history is off."""
    if cfg.history <= 0 or not tid:
        return
    local_store(provision=True).append(cfg, tid, role, text, **fields)


def history(tid):
    """The thread as chat messages [{"role","content"}], capped."""
    return local_store().history(tid)


def pick(cfg, more):
    """(thread id, history) for a turn: the newest thread continued when
    `more` asks for it, else a new one. (None, []) when history is off."""
    if cfg.history <= 0:
        return None, []
    return local_store(provision=True).pick(cfg, more)


def list_threads(n=5):
    """The newest n threads that hold a turn: [{"id","ts","title","turns"}]."""
    return local_store().list_threads(n)


def clear():
    """Remove every thread; how many."""
    return local_store().clear()


def prune(cfg):
    """Delete threads untouched for more than SPARK_HISTORY days."""
    local_store().prune(cfg)


# ------------------------------------------------------------------ claim
def claim_legacy(name, dk):
    """Move the pre-v1.4 plaintext threads into a user's sealed store:
    seal every message, prove the sealed copy opens, then remove the
    plaintext. Re-runnable; returns how many threads moved."""
    st = store_for(name, dk)
    moved = 0
    try:
        names = [f for f in os.listdir(THREADS_DIR) if f.endswith(".jsonl") and _ID.match(f[:-6])]
    except OSError:
        return 0
    for fname in sorted(names):
        tid, src = fname[:-6], os.path.join(THREADS_DIR, fname)
        msgs = []
        try:
            with open(src, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(d, dict) and d.get("role") and isinstance(d.get("text"), str):
                        msgs.append(d)
        except OSError:
            continue
        st._dir()
        if st.exists(tid):                     # a crashed earlier claim: re-seal fresh
            os.remove(st._path(tid))
        for d in msgs:
            vault.append_sealed(st._path(tid), dk, "thread", tid,
                                json.dumps(d, ensure_ascii=False).encode("utf-8"))
        if len(st.load(tid)) >= len(msgs):     # the sealed copy opens: safe to drop
            os.remove(src)
            moved += 1
    return moved


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
    return clip(data)


def clip(data):
    """At most FILE_MAX chars: the head, a cut mark that says how much is
    missing, the tail. The cut is always visible -- llama-server would
    otherwise drop the excess silently."""
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
def reply(cfg, thread, text, files=(), cwd="", shell="", mode="chat", on_delta=None, context="", line=None, brain=None,
          store=None, mem=None):
    """One turn, no terminal: the answer streams through on_delta(text).
    `thread` None starts one (None stays None when history is off);
    `files` are @FILE names as typed, read here relative to cwd and sent
    after `context` (piped output). Both messages land on the thread and
    the turn is recorded. `brain` goes to the Session (the FORGE's own
    upstream). Returns (thread, answer, ms). Raises RefError before any
    request, wire.BrainError from the request. A KeyboardInterrupt during
    the request (Ctrl-C at the prompt), or a BrokenPipeError /
    ConnectionResetError from on_delta (a page or desktop client pressing
    stop mid-stream), appends the user line and, when any text arrived,
    the partial reply (partial=True), then re-raises; the thread id rides
    on the exception (`e.thread`) so the caller can keep going with it.
    Nothing is printed here -- that is the caller's job."""
    from . import session          # session imports forge: resolved late on purpose
    context = "\n\n".join(c for c in (context, file_context(files, cwd)) if c)
    if not text and files:
        text = SUMMARISE
    if line is None:
        line = " ".join(["@" + f for f in files] + ([text] if text else []))
    st = store if store is not None else local_store(provision=cfg.history > 0)
    if thread is None:
        thread = st.new_thread(cfg)
    s = session.Session(cfg, mode, shell, cwd, st.history(thread) if thread else None, brain, mem=mem)
    tap = on_delta or (lambda d: None)
    collected = []

    def on_delta_tap(d):
        collected.append(d)
        tap(d)

    try:
        answer, ms = s.ask_stream(text, context, on_delta_tap)
    except (KeyboardInterrupt, BrokenPipeError, ConnectionResetError) as e:
        st.append(cfg, thread, "user", line, mode=mode, cwd=cwd)
        partial = "".join(collected)
        if partial:
            st.append(cfg, thread, "assistant", partial, kind="answer", partial=True)
        e.thread = thread
        raise
    s.record(kind="answer", ms=ms, thread=thread)
    st.append(cfg, thread, "user", line, mode=mode, cwd=cwd)
    st.append(cfg, thread, "assistant", answer, kind="answer")
    return thread, answer, ms


# ------------------------------------------------------------ chat history
def _chat_history_lines():
    """The prompt lines of earlier chats, decrypted from the account's
    sealed chat-history; the pre-v1.4 plaintext file is the fallback
    until the first sealed write removes it."""
    from . import CHAT_HISTORY_FILE, users
    try:
        name, _ = users.account()
        if name and users.exists(name):
            path = os.path.join(users.user_dir(name), "chat-history")
            dk = users.account_key()
            if dk and os.path.isfile(path):
                recs = vault.read_sealed(path, dk)
                return recs[0].decode("utf-8", "replace").splitlines() if recs else []
        with open(CHAT_HISTORY_FILE, encoding="utf-8", errors="replace") as f:
            return [ln for ln in f.read().splitlines() if ln]
    except (OSError, vault.SealError):
        pass
    return []


def _write_chat_history(readline):
    """The newest 500 prompt lines, sealed into the account's store; the
    legacy plaintext file is removed once the sealed copy is written --
    no plaintext of what you typed ever touches the disk again."""
    from . import CHAT_HISTORY_FILE
    try:
        n = readline.get_current_history_length()
        lines = [readline.get_history_item(i) for i in range(max(1, n - 499), n + 1)]
        blob = ("\n".join(ln for ln in lines if ln) + "\n").encode("utf-8")
        st = local_store(provision=True)
        if isinstance(st, _NullStore):
            return
        st._dir()
        vault.write_sealed(os.path.join(os.path.dirname(st.tdir), "chat-history"),
                           st.dk, "chathist", st.name, blob)
        try:
            os.remove(CHAT_HISTORY_FILE)
        except OSError:
            pass
    except Exception:
        log_exc("chat history")


# ------------------------------------------------------------------- chat
CHAT_USAGE = """%s chat -- a conversation

  spark chat <words>             one more turn on the newest thread, streamed
  spark chat --thread N [words]  an older thread instead: N from the /resume
                                 or spark history list (1 = newest), or a
                                 literal thread id
  spark chat                     a conversation at the `chat> ` prompt

  Inside it: @FILE words asks about a file; /help lists the verbs (/new,
  /resume, /clear, /last, /model); /q (or /quit, /exit, :q, quit, exit,
  bye, Ctrl-D) ends, silently; Ctrl-C cancels a reply in progress without
  ending the chat. Every turn is kept as a thread (spark history).
"""

# Any of these alone ends the conversation, silently. Generous on purpose:
# a quit word the REPL does not know goes to the model, which role-plays
# an exit while the prompt lives on -- a first-session trap.
QUIT_WORDS = ("/q", "/quit", "/exit", ":q", ":quit", ":wq", "quit", "exit", "bye")


def resolve_thread(tok, threads=None):
    """The thread id `tok` names: a 1-based index into the newest threads
    (the /resume listing, 1 = newest) or a literal thread id. None when
    it names nothing."""
    if threads is None:
        threads = list_threads(5)
    if tok.isdigit():
        n = int(tok)
        return threads[n - 1]["id"] if 1 <= n <= len(threads) else None
    return tok if exists(tok) else None


def _slash_help(cfg, thread, args):
    from . import say
    say("/help    this list")
    say("/new     a fresh thread")
    say("/resume  an older thread: bare lists the newest 5, /resume N picks")
    say("/clear   wipe the screen; the thread goes on")
    say("/last    the last turn, with its tok/s")
    say("/model   which model is answering")
    say("/q       end the conversation (Ctrl-D works too)")
    return thread


def _slash_new(cfg, thread, args):
    from . import MARK, say
    say("%s: a fresh thread" % MARK)
    return None


def _slash_resume(cfg, thread, args):
    from . import say
    if cfg.history <= 0:
        print("spark: history is off", file=sys.stderr, flush=True)
        return thread
    threads = list_threads(5)
    if not args:
        if not threads:
            say("(no threads yet)")
        for i, th in enumerate(threads, 1):
            say("%d) %d turn%s  %s" % (i, th["turns"], "" if th["turns"] == 1 else "s", th["title"]))
        return thread
    tid = resolve_thread(args[0], threads)
    if not tid:
        print("spark: no thread %s -- /resume lists them" % args[0], file=sys.stderr, flush=True)
        return thread
    users = [m for m in load(tid) if m["role"] == "user"]
    title = _title(users[0]["text"]) if users else tid
    say("* resuming: %s (%d turn%s)" % (title, len(users), "" if len(users) == 1 else "s"))
    return tid


def _slash_clear(cfg, thread, args):
    # The screen only: at a terminal the escapes wipe it (scrollback too)
    # and nothing else is printed -- the intro opens the conversation
    # exactly once. Piped, the escapes would be garbage, so nothing is
    # written at all. The thread goes on either way.
    if sys.stdout.isatty():
        sys.stdout.write("\033[2J\033[3J\033[H")
        sys.stdout.flush()
    return thread


def _slash_last(cfg, thread, args):
    from . import cli, say, session
    say(cli._fmt_turn(session.last_turn()))
    return thread


def _slash_model(cfg, thread, args):
    from . import cli, say, wire
    try:
        url, model, is_forge = wire.resolve_brain(cfg)
    except wire.BrainError as e:
        print("spark: " + e.hint, file=sys.stderr, flush=True)
        return thread
    # `ember:` only when an ember role is actually served; a one-model
    # machine (_role_rows says []) answers with that model, unlabelled.
    stem, label = model, "model"
    for role, s, _loaded in cli._role_rows(cfg, url, is_forge):
        if role == "ember":
            stem, label = s, "ember"
            break
    say("%s: %s via %s" % (label, stem, url))
    return thread


# /q is not here: QUIT_WORDS is checked first, so it never reaches this dict.
# Every verb takes (cfg, thread, args) and returns the thread to go on with.
SLASH_VERBS = {"/help": _slash_help, "/new": _slash_new, "/resume": _slash_resume,
               "/clear": _slash_clear, "/last": _slash_last, "/model": _slash_model}


def cmd_chat(args):
    from . import MARK, glyph, config, say, wire
    from . import cli
    if args and args[0] in ("-h", "--help", "help"):
        say(CHAT_USAGE.rstrip() % MARK)
        return 0
    picked = None
    if args and args[0] == "--thread":
        if len(args) < 2:
            say(CHAT_USAGE.rstrip() % MARK)
            return 2
        picked, args = args[1], args[2:]
    cfg = config.load()
    if picked is not None:
        if cfg.history <= 0:
            say("%s chat -- history is off (SPARK_HISTORY)" % MARK)
            return 2
        thread = resolve_thread(picked)
        if thread is None:
            say("%s chat -- no thread %s (spark history lists them)" % (MARK, picked))
            return 2
    else:
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
            for ln in _chat_history_lines():
                readline.add_history(ln)
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
                parts = text.split()
                verb = parts[0]
                fn = SLASH_VERBS.get(verb)
                if fn:
                    thread = fn(cfg, thread, parts[1:])
                else:
                    print("spark: no %s -- /help lists them" % verb, file=sys.stderr, flush=True)
                if verb != "/clear":
                    say()      # a blank line between turns; /clear starts clean
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
            _write_chat_history(readline)
    return 0
