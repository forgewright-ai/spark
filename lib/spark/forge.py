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
# A KEPT thread lives in kept/ beside threads/ (the same parent, the
# same header: the AAD is "thread <id>", so a move is a rename and every
# record still opens). Pruning, the header sweep and a clear read
# threads/ alone, so a kept thread stays past SPARK_HISTORY and takes
# appends when history is off. It leaves through unkeep (`/keep off`)
# or `spark user remove`. An id is in one directory, never both.
#
# reply() is one turn of the FORGE without a terminal: the prompt, the
# REPL and the page all go through it. `@FILE` words name files whose
# text rides along in the request's context slot.

import json
import os
import re
import sys
import time
from contextlib import contextmanager

from . import THREADS_DIR, log_exc, paint, state_dir, vault
from . import memory, persona, soul
from . import text as textmod

HISTORY_MAX_CHARS = 20000     # what a continued thread sends at most; oldest pairs go first
FILE_HEAD, FILE_TAIL = 4000, 12000
FILE_MAX = FILE_HEAD + FILE_TAIL  # what an @FILE sends at most: its head, a cut mark, its tail
SUMMARISE = "Summarise this file."  # the question when @FILE comes alone
TITLE_COLS = 60
# a thread id: a file name under the store, so a short plain word and
# never a path -- 1 to 64 letters, digits, - and _ (a timestamp id is 17,
# an app's pane id well under the cap)
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")     # always fullmatch: `$` alone takes "id\n"
# the most kept threads one user holds, so it can be argued with: a
# program keeping what it must not lose is one kept thread each, and a
# create past this is refused (full) rather than filling the disk
KEEP_MAX = 2000


class RefError(Exception):
    """An @FILE that cannot be sent; hint is the one line for a human."""

    def __init__(self, hint):
        super().__init__(hint)
        self.hint = hint


class KeepError(Exception):
    """A thread that cannot be kept or let go: kind full (KEEP_MAX),
    both (the id in threads/ and kept/ at once), store (the disk or no
    store at all); hint is the one line for a human or a program."""

    def __init__(self, kind, hint):
        super().__init__(hint)
        self.kind, self.hint = kind, hint


# --------------------------------------------------------------- identity
def identity(cfg, mem=None):
    """The soul, then the remembered facts when there are any. `mem`
    names whose facts (a memory.store_of tuple): the FORGE passes the
    requesting user's; None is this machine's own account."""
    t = soul.text(cfg) + served(cfg)
    m = memory.block(cfg, mem)
    return t + ("\n\n" + m if m else "")


def served(cfg):
    """One sentence naming the model this machine serves for a
    conversation (the chat model, else the line's), or "" where nothing is
    served here (a client: the machine it asks says it). Asked "what is
    your model", the 26B answered that it could not tell (2026-10-01)."""
    try:
        from . import engine
        files = engine.roles(cfg)
        f = files.get("ember") or files.get("spark")
        return ("\nThe model answering is %s, served on this machine." % engine.model_stem(f)) if f else ""
    except Exception:
        return ""


def system(cfg, mode, shell, mem=None):
    """The whole system message: machine facts, identity, the mode's task.
    Byte-stable per machine, shell and mode until the soul or memory
    changes. A conversation (chat) gets one machine line, not the shell
    brief -- see persona.mode_prefix."""
    return persona.mode_prefix(cfg, mode, shell) + "\n\n" + identity(cfg, mem) + "\n\n" + persona.MODES[mode]


# ---------------------------------------------------------------- threads
def valid_id(tid):
    return bool(tid) and isinstance(tid, str) and bool(_ID.fullmatch(tid))


def _title(s):
    s = " ".join((s or "").split())
    return s if len(s) <= TITLE_COLS else s[:TITLE_COLS - 3] + "..."


def _written(path):
    """Whether a thread file holds a record after its header. A header
    alone is a thread made and not yet written: a first turn that
    failed, or a thread a program made over the API."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            f.readline()
            return any(line.strip() for line in f)
    except OSError:
        return False


class Store:
    """One user's sealed thread store: the directory and the data key.
    Every read decrypts, every write seals; a caller without the key has
    no store. The module-level functions below are this machine's own.
    The regular threads live in `tdir`, the kept ones in `kdir`, a
    directory named kept beside it."""

    def __init__(self, tdir, dk, name=""):
        self.tdir, self.dk, self.name = tdir, dk, name
        self.kdir = os.path.join(os.path.dirname(tdir), "kept")

    def _dir(self, kept=False):
        if self.name:
            from . import users
            users.make_dirs(self.name)
        else:
            state_dir()
            os.makedirs(self.tdir, mode=0o700, exist_ok=True)
            try:
                os.chmod(self.tdir, 0o700)
            except OSError:
                pass
        if not kept:
            return self.tdir
        os.makedirs(self.kdir, mode=0o700, exist_ok=True)
        os.chmod(self.kdir, 0o700)
        return self.kdir

    def _in(self, d, tid):
        return os.path.join(d, tid + ".sealed")

    def _where(self, tid):
        """(path, kept): the kept file when there is one, else the regular
        path (where a new file goes). ValueError on a bad id."""
        if not valid_id(tid):
            raise ValueError("bad thread id: %r" % (tid,))
        k = self._in(self.kdir, tid)
        if os.path.isfile(k):
            return k, True
        return self._in(self.tdir, tid), False

    def _path(self, tid):
        return self._where(tid)[0]

    def exists(self, tid):
        return valid_id(tid) and (os.path.isfile(self._in(self.kdir, tid))
                                  or os.path.isfile(self._in(self.tdir, tid)))

    def is_kept(self, tid):
        return valid_id(tid) and os.path.isfile(self._in(self.kdir, tid))

    def _mint(self, d, other):
        """A fresh timestamp id with its file (header only) made now in
        `d`: two threads born in the same second get -2, -3, and an id
        the `other` directory holds is never taken. None past 99."""
        base = time.strftime("%Y-%m-%d-%H%M%S")
        for n in range(1, 100):
            tid = base if n == 1 else "%s-%d" % (base, n)
            if os.path.exists(self._in(other, tid)):
                continue
            try:
                fd = os.open(self._in(d, tid), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as f:
                    f.write(vault.header("thread", tid) + "\n")
                return tid
            except FileExistsError:
                continue
        return None

    def new_thread(self, cfg):
        """A fresh id, its file (header only) created now so two threads
        born in the same second get -2, -3. None when history is off."""
        if cfg.history <= 0:
            return None
        try:
            return self._mint(self._dir(), self.kdir)
        except OSError:
            log_exc("new thread")
        return None

    def open_thread(self, cfg, tid):
        """A thread under the caller's own id (the editor names its panes'
        threads: no id can come back through a raw text stream): created,
        header only, when absent. None when the id is not one
        (forge.valid_id), or when history is off and the thread is not
        kept."""
        if not valid_id(tid):
            return None
        if self.is_kept(tid):
            return tid
        if cfg.history <= 0:
            return None
        try:
            p = self._path(tid)
            self._dir()
            if not os.path.isfile(p):
                fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as f:
                    f.write(vault.header("thread", tid) + "\n")
            return tid
        except FileExistsError:
            return tid
        except OSError:
            log_exc("open thread")
            return None

    def _files(self, kept_only=False):
        """[(mtime_ns, id, kept)] of every thread file, unsorted: the
        regular ones and the kept ones, or the kept ones alone."""
        out = []
        dirs = ((self.kdir, True),) if kept_only else ((self.tdir, False), (self.kdir, True))
        for d, kept in dirs:
            try:
                names = os.listdir(d)
            except OSError:
                continue
            for name in names:
                if name.endswith(".sealed") and _ID.fullmatch(name[:-7]):
                    try:
                        out.append((os.stat(os.path.join(d, name)).st_mtime_ns, name[:-7], kept))
                    except OSError:
                        pass
        return out

    def last_thread(self, kept_only=False):
        """The id of the thread written last, kept or not (kept_only: the
        kept ones alone), or None. A file that is a header alone is
        skipped: a thread a program made and has not written yet is not
        what `??` goes on with."""
        for _, tid, kept in sorted(self._files(kept_only), reverse=True):
            if _written(self._in(self.kdir if kept else self.tdir, tid)):
                return tid
        return None

    def load(self, tid):
        """Every message of a thread: [{"ts","role","text",...}]. A record
        that does not open (or parse) is dropped, never fatal. A file
        whose header is not `thread tid` -- a renamed sealed file -- is
        refused whole, counted (self.refused) and reported to the debug
        log: read as another thread, its next append would fail its AAD
        in silence."""
        out = []
        try:
            for rec in vault.read_sealed(self._path(tid), self.dk, "thread", tid):
                try:
                    d = json.loads(rec.decode("utf-8"))
                except ValueError:
                    continue
                if isinstance(d, dict) and d.get("role") and isinstance(d.get("text"), str):
                    out.append(d)
        except vault.SealError:
            self.refused = getattr(self, "refused", 0) + 1
            log_exc("thread %s refused" % tid)
        except OSError:
            pass
        return out

    def append(self, cfg, tid, role, text, **fields):
        """One sealed message onto a thread: True when it was stored.
        False when history is off and the thread is not kept, or when the
        store failed (a seal or disk error, logged)."""
        if not tid:
            return False
        try:
            path, kept = self._where(tid)
        except ValueError:
            log_exc("append thread")
            return False
        if cfg.history <= 0 and not kept:
            return False
        d = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "role": role, "text": text}
        d.update(fields)
        try:
            self._dir(kept)
            vault.append_sealed(path, self.dk, "thread", tid,
                                json.dumps(textmod.clean(d), ensure_ascii=False).encode("utf-8"))
            return True
        except (OSError, vault.SealError):
            log_exc("append thread")
            return False

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
        """The newest n threads that hold a turn, kept or not:
        [{"id","ts","title","turns","kept"}]."""
        out = []
        for _, tid, kept in sorted(self._files(), reverse=True):
            msgs = self.load(tid)
            users = [m for m in msgs if m["role"] == "user"]
            if not users:
                continue
            out.append({"id": tid, "ts": users[0].get("ts", ""),
                        "title": _title(users[0]["text"]), "turns": len(users), "kept": kept})
            if len(out) >= n:
                break
        return out

    def kept_count(self):
        """How many kept threads: every kept/*.sealed, written or not --
        what KEEP_MAX counts."""
        return len(self._files(kept_only=True))

    def keep(self, tid=None):
        """Make a thread kept, with no model turn: (id, created). No id
        mints a timestamp one, header only; a new id is made header only;
        a regular thread is moved (a rename: the same header, so every
        record still opens); a kept one answers as it is. ValueError on a
        bad id; KeepError full past KEEP_MAX, both when the id is in both
        directories, store when the disk refuses."""
        if tid is not None and not valid_id(tid):
            raise ValueError("bad thread id: %r" % (tid,))
        kp = rp = ""
        inr = False
        if tid is not None:
            kp, rp = self._in(self.kdir, tid), self._in(self.tdir, tid)
            ink, inr = os.path.isfile(kp), os.path.isfile(rp)
            if ink and inr:
                raise KeepError("both", "thread %s is both kept and not: it is left as it is" % tid)
            if ink:
                return tid, False
        if self.kept_count() >= KEEP_MAX:
            raise KeepError("full", "%d kept threads is the most one user keeps: let one go first" % KEEP_MAX)
        try:
            d = self._dir(kept=True)
            if tid is None:
                tid = self._mint(d, self.tdir)
                if tid is None:
                    raise KeepError("store", "no free thread id this second: try again")
                return tid, True
            if inr:
                try:
                    os.rename(rp, kp)
                    return tid, False
                except FileNotFoundError:
                    # it moved or went while this looked: kept by another
                    # request is kept, gone is made anew below
                    if os.path.isfile(kp):
                        return tid, False
            fd = os.open(kp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(vault.header("thread", tid) + "\n")
            return tid, True
        except FileExistsError:
            return tid, False
        except OSError:
            log_exc("keep thread")
            raise KeepError("store", "the thread could not be kept -- see state/debug.log")

    def unkeep(self, tid):
        """A kept thread back among the regular ones (a rename), where
        SPARK_HISTORY ages it like any other. True when it moved, False
        when it was not kept; KeepError both or store."""
        if not self.is_kept(tid):
            return False
        kp, rp = self._in(self.kdir, tid), self._in(self.tdir, tid)
        if os.path.isfile(rp):
            raise KeepError("both", "thread %s is both kept and not: it is left as it is" % tid)
        try:
            self._dir()
            os.rename(kp, rp)
            return True
        except FileNotFoundError:
            return False
        except OSError:
            log_exc("let a thread go")
            raise KeepError("store", "the thread could not be let go -- see state/debug.log")

    def clear(self):
        """Remove every regular thread; how many. A kept thread stays."""
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
        """Delete regular threads untouched for more than SPARK_HISTORY
        days. A kept thread is never looked at."""
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

    def is_kept(self, tid):
        return False

    def new_thread(self, cfg):
        return None

    def open_thread(self, cfg, tid):
        return None

    def last_thread(self, kept_only=False):
        return None

    def load(self, tid):
        return []

    def append(self, cfg, tid, role, text, **fields):
        return False

    def history(self, tid):
        return []

    def pick(self, cfg, more):
        return None, []

    def list_threads(self, n=5):
        return []

    def kept_count(self):
        return 0

    def keep(self, tid=None):
        raise KeepError("store", "no store here: log in first (spark user login NAME)")

    def unkeep(self, tid):
        return False

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


def local_store(provision=False, cfg=None):
    """This machine's own store: the logged-in account's, unlocked by the
    account-key file. With provision=True a machine with no account mints
    one (write paths); without, reads answer empty instead. Returns a
    Store, or a _NullStore when there is none to be had. A CLIENT never
    mints (cfg.client, no login): the FORGE it answers from is the account
    authority -- spark user add NAME there, spark user login NAME here --
    and until then the turn is answered, not kept."""
    from . import users
    try:
        name, token = users.account()
        if not name and provision:
            from . import config
            if (cfg if cfg is not None else config.load()).client:
                return _NullStore()
        if name and not users.exists(name) and token:
            # a login without a store (a client, or a wiped users/): the
            # same token seals a fresh local store on first write
            if provision:
                d = users.user_dir(name)
                if os.path.isfile(os.path.join(d, "token.hash")):
                    # the store was provisioned once (token.hash is its
                    # marker) but its key file is gone: nothing minted
                    # here could read those files, and a stale
                    # account-key must never seal against a fresh key
                    from . import die
                    die("the account's key is gone -- spark user login %s again" % name, 78)
                users.write_login(name, token)      # keep the login
                users.make_dirs(name)
                ndk = vault.new_key()
                vault.write_private(os.path.join(d, "token.hash"),
                                    (vault.token_hash(token) + "\n").encode())
                vault.write_private(os.path.join(d, "key"),
                                    vault.wrap_key(ndk, token, name).encode())
                # refresh the cached account-key NOW, so account_key()
                # below answers the key just minted -- an earlier login's
                # stale cache must never seal what this key wraps
                users.write_login(name, token, ndk)
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
    return local_store(provision=True, cfg=cfg).new_thread(cfg)


def open_thread(cfg, tid):
    """The thread `tid` on this machine's own store, created when absent
    (the editor's `--thread`). None when history is off, unless the
    thread is kept."""
    if cfg.history <= 0:
        return tid if local_store().is_kept(tid) else None
    return local_store(provision=True, cfg=cfg).open_thread(cfg, tid)


def last_thread(kept_only=False):
    """The id of the thread written last (kept_only: the newest kept
    one), or None."""
    return local_store().last_thread(kept_only)


def load(tid):
    """Every message of a thread, decrypted: [{"ts","role","text",...}]."""
    return local_store().load(tid)


def append(cfg, tid, role, text, **fields):
    """One sealed message onto a thread: True when it was stored. Nothing
    when history is off, unless the thread is kept."""
    if not tid:
        return False
    return local_store(provision=cfg.history > 0).append(cfg, tid, role, text, **fields)


def is_kept(tid):
    """Whether this machine's own thread `tid` is a kept one."""
    return local_store().is_kept(tid)


def keep(tid):
    """Keep this machine's own thread `tid` (Store.keep): (id, created)."""
    return local_store().keep(tid)


def unkeep(tid):
    """Let this machine's own kept thread `tid` go (Store.unkeep)."""
    return local_store().unkeep(tid)


def kept_count():
    """How many kept threads this machine's own store holds."""
    return local_store().kept_count()


def history(tid):
    """The thread as chat messages [{"role","content"}], capped."""
    return local_store().history(tid)


def text_sha(data):
    """The short hash a thread's first user message carries in `text_sha`:
    which text this exchange is about."""
    import hashlib
    return hashlib.sha256(data.encode("utf-8", "replace")).hexdigest()[:16]


def same_text(tid, sha):
    """True when the thread's first user message carried a text of this
    sha. The rule every grounded contract's --thread follows: the same
    text again rides as the words alone, a changed one is sent again,
    labelled as it is now."""
    first = next((m for m in load(tid) if m.get("role") == "user"), {})
    return first.get("text_sha") == sha


def pick(cfg, more):
    """(thread id, history) for a turn: the newest thread continued when
    `more` asks for it, else a new one. (None, []) when history is off."""
    if cfg.history <= 0:
        return None, []
    return local_store(provision=True).pick(cfg, more)


# --------------------------------------------- the peer's own store (`??`)
def _peer_req(cfg, method, path, body=None):
    """One contract-9 request to the peer FORGE as this machine's login.
    (status, parsed json); (0, None) on any trouble -- the line must
    never block on thread plumbing."""
    import urllib.request
    from . import users
    token = users.account()[1]
    if not token or not cfg.peer_ai_url:
        return 0, None
    url = cfg.peer_ai_url.rstrip("/") + path
    headers = {"Authorization": "Bearer " + token}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers.update({"Content-Type": "application/json", "X-Spark": "1"})
    try:
        req = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.load(r)
    except Exception:
        return 0, None


def peer_newest(cfg):
    """The newest thread of the logged-in user's OWN store on the peer
    FORGE, as (tid, chat history) -- what a client's `??` continues, so
    the box's prompt, this prompt and the page share one thread (one
    identity, every door). None on any trouble: the local path answers
    as before."""
    if not cfg.client:
        return None
    st, d = _peer_req(cfg, "GET", "/api/threads?n=1")
    if st != 200 or not d or not d.get("threads"):
        return None
    tid = d["threads"][0].get("id")
    st, d = _peer_req(cfg, "GET", "/api/threads/%s" % tid)
    if st != 200 or not d:
        return None
    msgs = [{"role": m["role"], "content": m["text"]}
            for m in d.get("messages", []) if m.get("role") in ("user", "assistant")]
    total = sum(len(m["content"]) for m in msgs)
    while msgs and total > HISTORY_MAX_CHARS:
        total -= len(msgs.pop(0)["content"])
        if msgs and msgs[0]["role"] == "assistant":
            total -= len(msgs.pop(0)["content"])
    return tid, msgs


def peer_append(cfg, tid, role, text, **fields):
    """One message onto the peer thread `??` continued (POST
    /api/threads/<id>/append, the requester's own store). Quiet on
    failure -- the turn was answered; the record is best-effort, like
    every local append. No cwd ever rides: a client's paths stay home."""
    body = dict(fields, role=role, text=text)
    body.pop("cwd", None)
    _peer_req(cfg, "POST", "/api/threads/%s/append" % tid, body)


def list_threads(n=5):
    """The newest n threads that hold a turn, kept or not:
    [{"id","ts","title","turns","kept"}]."""
    return local_store().list_threads(n)


def clear():
    """Remove every regular thread; how many. A kept thread stays."""
    return local_store().clear()


def prune(cfg):
    """Delete regular threads untouched for more than SPARK_HISTORY days
    (a kept thread is never looked at)."""
    local_store().prune(cfg)


def _drop_stale_headers(tdir):
    """Remove header-only thread files older than a day: a failed first
    turn leaves them, and the header is plaintext -- no key needed to
    see that nothing follows it. `tdir` is a store's threads/, never its
    kept/: a kept thread a program made and has not written yet stays."""
    try:
        cutoff = time.time() - 86400
        for n in os.listdir(tdir):
            if not n.endswith(".sealed"):
                continue
            p = os.path.join(tdir, n)
            try:
                if os.path.getmtime(p) >= cutoff or os.path.getsize(p) > 200:
                    continue
                with open(p, encoding="utf-8", errors="replace") as f:
                    lines = [l for l in f.read().splitlines() if l.strip()]
                if len(lines) <= 1:
                    os.remove(p)
            except OSError:
                pass
    except OSError:
        pass


def prune_stores(cfg, keys):
    """The FORGE's prune: the box account's store and every named user's
    whose data key the server holds ({name: dk} -- a session or a cached
    bearer). A named store with no key in memory is skipped and counted
    (returned); its header-only leftovers still go, aged a day, because
    the header is plaintext."""
    from . import users
    local_store().prune(cfg)
    own = users.account()[0]
    skipped = 0
    for name in users.list_users():
        if name != own:
            dk = keys.get(name)
            if dk is not None:
                store_for(name, dk).prune(cfg)
            else:
                skipped += 1
        _drop_stale_headers(os.path.join(users.user_dir(name), "threads"))
    return skipped


# ------------------------------------------------------------------ claim
def claim_legacy(name, dk):
    """Move the pre-v1.4 plaintext threads into a user's sealed store:
    seal every message, prove the sealed copy opens, then remove the
    plaintext. Re-runnable; returns how many threads moved."""
    st = store_for(name, dk)
    moved = 0
    try:
        names = [f for f in os.listdir(THREADS_DIR) if f.endswith(".jsonl") and _ID.fullmatch(f[:-6])]
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
        if st.is_kept(tid):
            # claimed once and kept since: that sealed copy is the one to
            # keep, never re-sealed over; the plaintext goes when it opens
            if len(st.load(tid)) >= len(msgs):
                os.remove(src)
                moved += 1
            continue
        if st.exists(tid):                     # a crashed earlier claim: re-seal fresh
            os.remove(st._path(tid))
        for d in msgs:
            vault.append_sealed(st._path(tid), dk, "thread", tid,
                                json.dumps(textmod.clean(d), ensure_ascii=False).encode("utf-8"))
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
    return clip(file_text(name, cwd))


def file_text(name, cwd=""):
    """The whole text of one @FILE, relative to cwd (~ expanded), uncut
    (the chat's /read cuts it into contract 11's parts). The same
    refusals as read_file: a directory, a missing file, a binary."""
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
    return data


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
          store=None, mem=None, said=None):
    """One turn, no terminal: the answer streams through on_delta(text).
    `thread` None starts one (None stays None when history is off);
    `files` are @FILE names as typed, read here relative to cwd and sent
    after `context` (piped output). Both messages land on the thread and
    the turn is recorded. `brain` goes to the Session (the FORGE's own
    upstream). Returns (thread, answer, ms). Raises RefError before any
    request, wire.BrainError from the request. Any end mid-stream -- a
    KeyboardInterrupt (Ctrl-C at the prompt), a BrokenPipeError /
    ConnectionResetError from on_delta (a page or desktop client pressing
    stop), or a BrainError of kind `cut` (the server died with the answer
    half sent) -- appends the user line and, when any text arrived, the
    partial reply (partial=True), then re-raises; the thread id rides on
    the exception (`e.thread`) so the caller can keep going with it. Every
    other BrainError failed before a byte came back and leaves the thread
    as it was. `said` (a list), when given, gains the turn's two
    messages as the thread keeps them -- the chat's memory when no thread
    does (history off). Nothing is printed here -- that is the caller's job."""
    from . import session          # session imports forge: resolved late on purpose
    from . import wire
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

    def land(e):
        """The user line, and whatever words arrived, on the thread; the
        id rides on the exception so the caller keeps the thread."""
        st.append(cfg, thread, "user", line, mode=mode, cwd=cwd)
        partial = "".join(collected)
        if partial:
            st.append(cfg, thread, "assistant", partial, kind="answer", partial=True)
        e.thread = thread

    try:
        # the reply cap (cfg.max_tokens: 1200, or SPARK_MAX_TOKENS); a cap
        # that ends a reply is said out loud below
        answer, ms = s.ask_stream(text, context, on_delta_tap, max_tokens=cfg.max_tokens)
    except (KeyboardInterrupt, BrokenPipeError, ConnectionResetError) as e:
        land(e)
        raise
    except wire.BrainError as e:
        # a server that dies mid-reply is that same stop, arriving as an
        # error: the words already on the screen belong on the thread, and
        # a turn the user watched must not vanish with the connection.
        # Every other kind failed before a byte came back.
        if e.kind != "cut":
            raise
        land(e)
        raise
    if (s.timings or {}).get("finish") == "length":
        # the cap ended the reply, not the model: say so on the screen
        # (never on the thread -- the record keeps the words that came)
        from . import glyph
        tap("\n%s cut at the reply's length -- say: go on" % glyph("warn"))
        collected.pop()      # said on the screen, not kept on the thread
    # chars is a count, never the text: with tg_n it is this model's
    # characters a token, what `auto` paces a reply by
    s.record(kind="answer", ms=ms, thread=thread, chars=len(answer))
    st.append(cfg, thread, "user", line, mode=mode, cwd=cwd)
    st.append(cfg, thread, "assistant", answer, kind="answer")
    if said is not None:
        said.extend([{"role": "user", "text": line}, {"role": "assistant", "text": answer}])
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
                recs = vault.read_sealed(path, dk, "chathist", name)
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
        path = os.path.join(os.path.dirname(st.tdir), "chat-history")
        if os.path.isfile(path):
            # a sealed file that does not open (a flipped byte, a stale
            # account-key) is never written over: the save is skipped,
            # said once, and the file stays as it is
            try:
                vault.read_sealed(path, st.dk, "chathist", st.name)
            except (OSError, vault.SealError):
                print("! this chat cannot be opened -- spark user login",
                      file=sys.stderr, flush=True)
                return
        vault.write_sealed(path, st.dk, "chathist", st.name, blob)
        try:
            os.remove(CHAT_HISTORY_FILE)
        except OSError:
            pass
    except Exception:
        log_exc("chat history")


# ------------------------------------------------------------------- chat
CHAT_USAGE = """%s chat -- talk with the model

  spark chat                     go on with the newest thread
  spark chat <words>             one more turn on the newest thread
  spark chat --thread N [words]  an older thread: N from spark history
                                 (1 is the newest), or its id
  spark chat --reveal [N|auto|off]
                                 the reply pace: N characters a second,
                                 auto, or off (as it comes)

  Inside: @FILE asks about a file, /help lists the commands, and Esc,
  Ctrl-D or /q ends it. Ctrl-C stops a reply. With the voice on, Esc v
  listens and Esc x stops the speaking. A chat is kept for SPARK_HISTORY
  days; /keep keeps it longer.
"""

# Any of these alone ends the conversation. Generous on purpose: a quit
# word the REPL does not know goes to the model, which role-plays an
# exit while the prompt lives on -- a first-session trap.
QUIT_WORDS = ("/q", "/quit", "/exit", ":q", ":quit", ":wq", "quit", "exit", "bye")

# This chat's own turns since it began (or since /new), in memory only:
# what /copy and /save take when no thread keeps them (SPARK_HISTORY=0)
# -- the replies on the screen this session, gone when the chat ends.
SAID = []
CONTINUING_COLS = 79    # the opening line fits 80 columns
SAVE_MAX = 99           # ~/spark-chat-DATE.txt, then -2 .. -99
# The chat's voice (SPARK_VOICE, at a terminal): `reader` is a
# voice.Reader while the mode is on or clear, None while off. Both speak
# every reply from the start (/aloud turns that off and on); clear speaks
# the opening and the refusals too. Every spoken line is printed as well. A reply is
# spoken as it streams, a sentence at a time (_Spoken, voice.Sentences),
# each one once the reveal printed it.
VOICE = {"reader": None, "mode": "off", "aloud": False}


def _tell(line):
    """One line of the chat's own, after the mark."""
    from . import say
    say(paint("*", "accent") + " " + line)


def _land(cfg, thread, asked, said, user=None, assistant=None):
    """One exchange of the chat's own (/read, /do) on the chat's thread --
    a new one when there is none yet, so it is the newest -- and in SAID.
    Returns the thread to go on with."""
    if thread is None:
        thread = new_thread(cfg)
    if thread:
        append(cfg, thread, "user", asked, **(user or {}))
        append(cfg, thread, "assistant", said, **(assistant or {}))
    SAID.extend([{"role": "user", "text": asked}, {"role": "assistant", "text": said}])
    return thread


def _voice_setup(cfg, tty):
    """The chat's voice for this conversation (VOICE): at a terminal only."""
    from . import voice
    VOICE.update(reader=None, mode="off", aloud=False)
    if not tty:
        return
    try:
        m = voice.mode(cfg)
    except Exception:       # noqa: BLE001 -- the voice never breaks the chat
        m = "off"
    if m != "off":
        VOICE.update(reader=voice.Reader(cfg), mode=m, aloud=True)
        VOICE["reader"].warm()      # the engine loads while the person types


def _aloud(text, cut=False):
    """The text spoken too (the reader's thread: the prompt never waits)."""
    if VOICE["reader"] is not None and text:
        VOICE["reader"].put(text, cut=cut)


# The text follows the voice (a reply read aloud, the reveal on, at a
# terminal of this machine): a sentence's text is shown as its sound
# starts, spread over FOLLOW_SHARE of its length -- FOLLOW_EARLY seconds
# ahead, since a word is drawn once it is whole. A sentence whose sound
# is not known within FOLLOW_WAIT seconds lets the text go on at the
# chosen pace for the rest of the reply.
FOLLOW_WAIT = 8.0
FOLLOW_SHARE = 0.9
FOLLOW_EARLY = 0.3

# The face talks (a reply read aloud, at a terminal where the look's
# motion and words are active): the reply opens with the idle face in the
# mark's place, and while one of its sentences sounds the mouth opens and
# closes every MOUTH_STEP seconds. Between sentences, after the last, on
# a cut (Esc x) and once a key is typed at `chat>`, it rests on idle.
MOUTH_STEP = 0.15
FACE = [None]           # the talking face of the newest reply, while it may move


def _face_rest():
    """The face rests on idle and moves no more: a key typed, a reply
    stopped, the chat about to print a line of its own."""
    f, FACE[0] = FACE[0], None
    if f is not None:
        f.rest()


class _Face:
    """The talking face of one spoken reply, and the stream the wrap
    writes it through: every write is counted in rows (a line feed, a line
    the terminal wrapped), under one lock with the mouth's redraw. The
    redraw saves the cursor, goes up the rows the reply has taken to its
    first row, writes the frame there and restores -- only while that row
    is on screen (rows < the terminal's height - 1) and the terminal has
    kept its size. The thread ends resting on idle, once no line of the
    reply will sound again or rest() is called."""

    def __init__(self, stream, idle, talk, reader):
        import threading
        self.stream, self.reader = stream, reader
        self.frames = (paint(idle, "accent", stream), paint(talk, "accent", stream))
        self.lead = self.frames[0] + " "
        self.lock = threading.Lock()
        self.rows = self.col = 0
        self.size = self._size()
        self.started = False        # the lead is written: the row exists
        self.open = False           # the talking frame is the one drawn
        self.tags = []
        self.closed = self.halt = False
        self.thread = threading.Thread(target=self._run, name="spark-face", daemon=True)

    def _size(self):
        try:
            return tuple(os.get_terminal_size(self.stream.fileno()))
        except (AttributeError, OSError, ValueError):
            return (80, 24)

    # --- the stream the wrap writes through
    def isatty(self):
        return self.stream.isatty()

    def fileno(self):
        return self.stream.fileno()

    def flush(self):
        self.stream.flush()

    def write(self, s):
        with self.lock:
            self.started = self.started or bool(s)
            self._count(s)
            self.stream.write(s)

    def line(self):
        """A blank line of the chat's own after the reply, counted."""
        self.write("\n")
        self.flush()

    def _count(self, s):
        """(the lock held) The cursor's row below the lead and its column
        after `s`: a line feed, or a character past the last column, is
        a row more (a wide character two columns, an escape none)."""
        import unicodedata
        width = self.size[0]
        for ch in textmod.SGR_RE.sub("", s):
            if ch == "\n":
                self.rows, self.col = self.rows + 1, 0
            elif ch == "\r":
                self.col = 0
            elif ch == "\t":
                self.col = min(width, (self.col // 8 + 1) * 8)
            elif ch >= " " and not unicodedata.combining(ch):
                w = 2 if unicodedata.east_asian_width(ch) in "WF" else 1
                if self.col + w > width:
                    self.rows, self.col = self.rows + 1, 0
                self.col += w

    # --- the mouth
    def add(self, tags):
        with self.lock:
            self.tags.extend(t for t in tags if t is not None)

    def close(self):
        """No more lines come: the thread ends once none sounds."""
        self.closed = True

    def start(self):
        self.thread.start()
        return self

    def rest(self):
        """Idle now, and no redraw after it."""
        with self.lock:
            if self.open:
                self._draw(False)
            self.halt = True

    def _draw(self, talking):
        """(the lock held) The frame on the lead's row. Skipped while the
        cursor waits at the last column (a restore there may lose the
        wrap); False when that row is out of reach -- scrolled off, the
        terminal resized -- and the face moves no more."""
        if not self.started or self.col >= self.size[0]:
            return True
        if self.rows >= self.size[1] - 1 or self._size() != self.size:
            self.halt = True
            return False
        up = "\033[%dA" % self.rows if self.rows else ""
        self.stream.write("\x1b7" + up + "\r" + self.frames[talking] + "\x1b8")
        self.stream.flush()
        self.open = talking
        return True

    def _run(self):
        flip = 0.0
        try:
            while True:
                with self.lock:
                    tags = list(self.tags)
                    closed = self.closed
                now_ = self.reader.sounds(tags, MOUTH_STEP)
                with self.lock:
                    if self.halt:
                        return
                    now = time.monotonic()
                    if now_ == "now":
                        if now >= flip:
                            self._draw(not self.open)
                            flip = now + MOUTH_STEP
                    elif self.open:
                        self._draw(False)
                    if closed and not now_ and not self.open:
                        self.halt = True
                        return
        except Exception:   # noqa: BLE001 -- a face is never a reason to fail
            log_exc("forge: the talking face")


class _Spoken:
    """A reply spoken sentence by sentence: voice.Sentences into the
    reader. The first sentence cuts what the reader still says, so a new
    reply never waits behind an old one. Clear mode says a code block as
    "a code block, N lines"; mode on skips it.

    Two ways. feed() is handed the text once it is shown, so the voice
    follows the screen. begin() (cli.stream_turn, the reveal on at a
    terminal here) turns it around: take() hands each sentence to the
    reader the moment the model wrote it, and a thread of its own shows
    its text as its sound starts, at the voice's pace; end() waits until
    the last is shown, stop() ends it. face=True (the chat's reply):
    screen() gives the wrap its stream and its lead, the talking face
    where the look draws one."""

    def __init__(self, face=False):
        from . import voice
        self.split = voice.Sentences(code=VOICE["mode"] == "clear")
        self.first = True
        self.want_face = face
        self.face = None

    def screen(self):
        """(stream, lead) for the reply's wrap: the talking face's own
        stream and the idle face as the lead at a terminal where the
        look's motion and words are active; else stdout and no lead, the
        bytes as they were."""
        from . import look
        _face_rest()
        out = sys.stdout
        try:
            if not (self.want_face and VOICE["reader"] is not None and look.active("motion", out)
                    and look.active("words", out)):
                return out, None
            idle = look.faces()["idle"]
            self.face = _Face(out, idle, look.talking(idle) or idle, VOICE["reader"]).start()
        except Exception:   # noqa: BLE001 -- a face is never a reason to fail
            log_exc("forge: the talking face")
            return out, None
        FACE[0] = self.face
        return self.face, self.face.lead

    def feed(self, delta):
        self._put(self.split.feed(delta))

    def flush(self):
        self._put(self.split.flush())
        self._closed()

    def _closed(self):
        if self.face is not None:
            self.face.close()

    def _put(self, sentences):
        tags = []
        for s in sentences:
            tag = None
            if VOICE["reader"] is not None:
                tag = VOICE["reader"].put(s, cut=self.first)
                self.first = False
            tags.append(tag)
        if self.face is not None:
            self.face.add(tags)
        return tags

    @staticmethod
    def follows():
        """The text may follow the voice: a session on this machine. Over
        ssh the sound plays where spark runs, not where the person reads."""
        return not (os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"))

    def begin(self, wrap, busy):
        import threading
        self.wrap, self.busy, self.cps = wrap, busy, wrap.cps
        self.raw, self.marks, self.shown = "", [], 0
        self.done = self.halt = self.loose = False
        self.cv = threading.Condition()
        self.thread = threading.Thread(target=self._show_all, name="spark-reply-follow", daemon=True)
        self.thread.start()

    def take(self, delta):
        """(the stream's thread) A chunk of the reply: its sentences to
        the reader now, its text to the screen as they sound."""
        with self.cv:
            self.raw += delta
            self._mark(self.split.feed(delta))

    def _mark(self, sentences):
        """(the lock held) Each sentence queued, its end in the text kept
        with its tag."""
        ends = self.split.ends()
        self.marks += zip(ends, self._put(sentences))
        self.cv.notify_all()

    def end(self):
        """(the stream's thread) The reply is whole: the rest to the
        reader, and back once its text is all shown."""
        with self.cv:
            self._mark(self.split.flush())
            self.done = True
            self.cv.notify_all()
        self._closed()
        while self.thread.is_alive():
            self.thread.join(0.2)       # Ctrl-C lands between the waits
        self._rest()

    def stop(self, rest=False):
        """The text stops following. Ctrl-C: what was not shown stays
        unshown, as the reveal always did. The model gone mid-reply
        (rest=True): what came is shown at once."""
        with self.cv:
            self.halt = True
            self.cv.notify_all()
        self._closed()
        self.thread.join(2.0)
        if rest:
            self._rest()

    def _rest(self):
        if self.thread.is_alive() or self.shown >= len(self.raw):
            return
        self.busy.stop()
        self.wrap.pace(0)
        self.wrap.feed(self.raw[self.shown:])
        self.shown = len(self.raw)

    def _show_all(self):
        try:
            while True:
                with self.cv:
                    while not (self.halt or self.marks or self.done):
                        self.cv.wait()
                    if self.halt:
                        return
                    if self.marks:
                        end, tag = self.marks.pop(0)
                    elif self.shown < len(self.raw):
                        end, tag = len(self.raw), None      # a tail that is no sentence (marks alone)
                    else:
                        return
                    text = self.raw[self.shown:end]
                self._show(text, tag)
        except Exception:  # noqa: BLE001 -- the stream's thread shows the rest (end)
            log_exc("forge: the text following the voice")

    def _show(self, text, tag):
        """One sentence's text: when its sound starts, at the pace that
        ends it with FOLLOW_SHARE of its sound; at the chosen pace when it
        has none, or the voice fell behind."""
        from . import reveal
        pace = 0
        if tag is not None and not self.loose and VOICE["reader"] is not None:
            got = VOICE["reader"].when(tag, FOLLOW_WAIT, halt=lambda: self.halt)
            if got is False and not self.halt:
                self.loose = True
            elif got:
                starts, secs = got
                starts -= FOLLOW_EARLY
                while not self.halt and time.monotonic() < starts:
                    time.sleep(max(0.0, min(0.05, starts - time.monotonic())))
                pace = len(text.strip()) / max(secs * FOLLOW_SHARE, 0.1)
                pace = min(max(pace, reveal.CPS_MIN), reveal.CPS_MAX)
        self.wrap.pace(pace or self.cps)
        self.busy.stop()
        for i in range(0, len(text), 8):
            if self.halt:
                return
            self.wrap.feed(text[i:i + 8])
            self.shown += len(text[i:i + 8])


def _spoken():
    """A _Spoken for the reply about to stream, or None: the voice off,
    or mode on without /aloud. Its face talks where the look draws one."""
    return _Spoken(face=True) if VOICE["reader"] is not None and VOICE["aloud"] else None


def _aloud_reply(text):
    """A whole reply spoken through the same splitter (/again, /read)."""
    if VOICE["reader"] is not None and text:
        s = _Spoken()
        s.feed(text)
        s.flush()


def _hush():
    """Esc x: the speaking stops, here and in any other spark."""
    from . import voice
    if VOICE["reader"] is not None:
        return VOICE["reader"].hush()
    return voice.stop()


def _hear():
    """Esc v: (the words heard, as one line for `chat>`, or '';
    what to say when there are none, or '')."""
    from . import voice
    if VOICE["reader"] is None:
        return "", "! the voice is off -- spark voice on, then Esc v"
    VOICE["reader"].hush()          # spark does not hear itself
    try:
        text, _lang = voice.listen(VOICE["reader"].cfg)
    except voice.VoiceError as e:
        return "", "! " + str(e)
    except KeyboardInterrupt:
        return "", ""
    text = voice.heard_line(text)
    return text, ("" if text else "* nothing heard")


def _ended(e):
    """A SystemExit inside a readline callback (voice.listen's SIGHUP or
    SIGTERM: its recorder already stopped, its directory gone) cannot
    raise through C: the signal is delivered again with its default
    action, and the exit code is the fallback."""
    import signal
    code = e.code if isinstance(e.code, int) else 1
    if code - 128 in (signal.SIGHUP, signal.SIGTERM):
        try:
            signal.signal(code - 128, signal.SIG_DFL)
            os.kill(os.getpid(), code - 128)
        except (OSError, ValueError):
            pass
    os._exit(code)


def _listening():
    """The line Esc v shows while it listens."""
    return "* listening -- a pause ends it"


def _refuse(hint):
    """A refusal inside the chat: `! <hint>` on stderr, so a piped chat's
    stdout keeps the replies alone. Clear mode reads it aloud too."""
    if VOICE["mode"] == "clear":
        _aloud(hint)
    print("! " + hint, file=sys.stderr, flush=True)


def continuing(msgs):
    """The opening line of a chat that goes on with a thread: its first
    user message's first words, cut at a word so the line fits 80
    columns. '' for a thread with no user message."""
    from . import glyph
    first = next((m for m in msgs if m.get("role") == "user"), None)
    if first is None:
        return ""
    head, tail = '* continuing "', '" -- /new starts fresh, Esc ends'
    room = CONTINUING_COLS - len(head) - textmod.cols(tail)
    words = " ".join(textmod.scrub(first.get("text", "")).split())
    # a turn's own tags ([explain], [cwd /x]) are not the user's words:
    # skip them, and name the tag itself when nothing else is left
    tags = re.match(r"^((?:\[[^\]]*\]\s*)+)", words)
    if tags:
        rest = words[tags.end():].strip()
        words = rest or tags.group(1).strip().split("]")[0].lstrip("[").split()[0]
    if textmod.cols(words) > room:      # columns, not characters: a wide one takes two
        cut = glyph("cut")
        words = textmod.cut_cols(words, room - textmod.cols(cut))
        if " " in words:
            words = words[:words.rfind(" ")]
        words = words.rstrip() + cut
    return head + words + tail


def chat_model(cfg):
    """The chat model's name from what spark already knows -- the cached
    brain's roles, else this machine's own model files -- never a
    request, so the opening waits on nothing. '' when nothing says."""
    from . import config, engine, wire
    roles = wire.brain_roles(cfg)
    stem = roles.get("ember") or roles.get("spark") or ""
    if not stem and not cfg.client:
        stem = engine.model_file(cfg, "ember") or engine.model_file(cfg)
    return config.model_name(stem) if stem else ""


def opening(cfg, thread):
    """The chat's one opening line: the thread it goes on with, else the
    model it talks to."""
    msgs = load(thread) if thread else []
    if msgs:
        line = continuing(msgs)
        if line:
            return line
    name = chat_model(cfg)
    return "* chat%s -- Esc ends, /help lists commands" % (" with " + name if name else "")


def _opening(cfg, thread):
    """The opening at a terminal; clear mode reads it aloud."""
    from . import say
    say(opening(cfg, thread))
    if VOICE["mode"] == "clear":
        _aloud("chat. Escape ends it; slash help lists the commands.")


def _last_reply(thread):
    """This chat's last reply: from what it said, else from its thread."""
    for m in reversed(SAID):
        if m.get("role") == "assistant" and m.get("text"):
            return m["text"]
    for m in reversed(load(thread) if thread else []):
        if m.get("role") == "assistant" and m.get("text"):
            return m["text"]
    return ""


def number(tok):
    """Whether `tok` is a plain number, 0-9 alone: str.isdigit() says yes
    to `²` and other Unicode digits, which int() then refuses."""
    return tok.isascii() and tok.isdigit()


def resolve_thread(tok, threads=None):
    """The thread id `tok` names: a 1-based index into the newest threads
    (the /resume listing, 1 = newest) or a literal thread id. None when
    it names nothing."""
    if threads is None:
        threads = list_threads(5)
    if number(tok):
        n = int(tok)
        return threads[n - 1]["id"] if 1 <= n <= len(threads) else None
    return tok if exists(tok) else None


HELP = ("/new      start a new thread",
        "/resume   list older threads; /resume N goes back to one",
        "/clear    clear the screen",
        "/keep     keep this thread; /keep off lets it go",
        "/last     the last turn and its speed",
        "/model    the model answering",
        "/reveal   the reply pace: /reveal N, auto or off",
        "/copy     copy the last reply; /copy N an older one",
        "/save     save the chat to a file: /save [FILE]",
        "/read     /read @FILE [question]: an answer from the file",
        "/do       /do GOAL: a task here, step by step",
        "/aloud    read replies aloud, or stop",
        "/again    the last reply again",
        "/q        end the chat (Esc or Ctrl-D too)",
        "Esc v     listen; Esc x stops the speaking")


def _slash_help(cfg, thread, args):
    from . import say
    for line in HELP:
        say(line)
    return thread


def _slash_aloud(cfg, thread, args):
    if args not in ([], ["on"], ["off"]):
        _refuse("/aloud takes on or off")
        return thread
    want = (not VOICE["aloud"]) if not args else args == ["on"]
    if want and VOICE["reader"] is None:
        # the voice is off: this chat speaks anyway, until it ends
        from . import voice
        now = voice.for_now(cfg)
        if now is None:
            _refuse("no voice here yet -- spark voice on downloads it")
            return thread
        VOICE.update(reader=voice.Reader(now), mode=voice.mode(now))
        VOICE["reader"].warm()
    VOICE["aloud"] = want
    if want:
        _tell("replies aloud -- /aloud stops")
    else:
        if VOICE["reader"] is not None:
            VOICE["reader"].hush()
        _tell("replies quiet -- /aloud speaks them")
    return thread


def _slash_again(cfg, thread, args):
    # the thread keeps the model's own bytes: its escapes and controls go
    # before the terminal or the voice has them
    last = textmod.printable(_last_reply(thread))
    if not last:
        _refuse("no reply yet")
        return thread
    _tell(last)
    if VOICE["reader"] is not None:
        _aloud_reply(last)
    return thread


def _slash_new(cfg, thread, args):
    _tell("new thread")
    del SAID[:]
    return None


def _slash_resume(cfg, thread, args):
    from . import say
    if cfg.history <= 0:
        _refuse("history is off")
        return thread
    threads = list_threads(5)
    if not args:
        if not threads:
            _tell("no threads yet")
        for i, th in enumerate(threads, 1):
            say("%d) %d turn%s  %s" % (i, th["turns"], "" if th["turns"] == 1 else "s", th["title"]))
        return thread
    tid = resolve_thread(args[0], threads)
    if not tid:
        _refuse("no thread %s -- /resume lists them" % args[0])
        return thread
    users = [m for m in load(tid) if m["role"] == "user"]
    title = _title(users[0]["text"]) if users else tid
    _tell('continuing "%s" (%d turn%s)' % (title, len(users), "" if len(users) == 1 else "s"))
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


def _slash_keep(cfg, thread, args):
    # /keep moves the current thread into kept/ (pruning and a clear never
    # look there), /keep off moves it back to age like any other. The
    # thread goes on either way: only where its file lives changes.
    if args not in ([], ["off"]):
        _refuse("/keep takes nothing, or off")
        return thread
    if not thread:
        _refuse("history is off -- no thread to keep" if cfg.history <= 0 else "no thread yet -- ask something first")
        return thread
    try:
        if args == ["off"]:
            if unkeep(thread):
                _tell("let go -- it ages out like the rest")
            return thread
        keep(thread)
    except KeepError as e:
        _refuse(e.hint)
        return thread
    _tell("kept -- /keep off lets it go")
    return thread


def _slash_last(cfg, thread, args):
    from . import cli, say, session
    say(cli._fmt_turn(session.last_turn()))
    return thread


def _slash_model(cfg, thread, args):
    from . import cli, config, wire
    try:
        url, model, is_forge = wire.resolve_brain(cfg)
    except wire.BrainError as e:
        _refuse(e.hint)
        return thread
    # `ember:` only when an ember role is actually served; a one-model
    # machine (_role_rows says []) answers with that model, unlabelled.
    stem = next((s for role, s, _loaded in cli._role_rows(cfg, url, is_forge) if role == "ember"), model)
    _tell("%s at %s" % (config.model_name(stem), url))
    return thread


# /q is not here: QUIT_WORDS is checked first, so it never reaches this dict.
# Every verb takes (cfg, thread, args) and returns the thread to go on with.
REVEAL = [0]           # the chat's pace: 0 (as the chunks come, the default) | auto | N (/reveal, --reveal, SPARK_REVEAL)


def _slash_reveal(cfg, thread, args):
    from . import reveal
    if not args:
        # the benchmark: what the model writes, the threshold under it,
        # and what this chat does now -- the choice stays yours
        for ln in reveal.pace_report(cfg, REVEAL[0]):
            _tell(ln)
        return thread
    word = args[0]
    if word not in ("off", "auto"):
        try:
            n = int(word)
        except ValueError:
            n = -1
        if not reveal.CPS_MIN <= n <= reveal.CPS_MAX:
            _refuse("/reveal takes N (%d to %d), auto or off" % (reveal.CPS_MIN, reveal.CPS_MAX))
            return thread
        word = n
    REVEAL[0] = 0 if word == "off" else word
    _tell(reveal.pace_said(cfg, REVEAL[0]))
    return thread


def _turns(cfg, thread, verb):
    """The chat's user and assistant messages, oldest first; None, with
    the refusal said, when there are none to take. No thread (history
    off): the turns this chat said since it began or since /new (SAID)."""
    msgs = [m for m in load(thread) if m.get("role") in ("user", "assistant")] if thread else list(SAID)
    if msgs:
        return msgs
    _refuse("nothing to %s yet" % verb.lstrip("/"))
    return None


def clipboard():
    """The argv of this machine's clipboard: pbcopy on macOS, wl-copy
    under Wayland, xclip or xsel under X; None on a console or over ssh."""
    import shutil
    if sys.platform == "darwin" and shutil.which("pbcopy"):
        return ["pbcopy"]
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
        return ["wl-copy"]
    if os.environ.get("DISPLAY"):
        if shutil.which("xclip"):
            return ["xclip", "-selection", "clipboard"]
        if shutil.which("xsel"):
            return ["xsel", "-b"]
    return None


def _slash_copy(cfg, thread, args):
    # a reply's text as the thread keeps it (the model's own bytes, no
    # wrap and no escape) to the clipboard tool on its stdin; the tool's
    # own output goes nowhere (xclip and wl-copy stay behind to serve it)
    import subprocess
    if len(args) > 1 or (args and not (number(args[0]) and int(args[0]) >= 1)):
        _refuse("/copy N copies the Nth reply from the end")
        return thread
    n = int(args[0]) if args else 1
    msgs = _turns(cfg, thread, "/copy")
    if msgs is None:
        return thread
    replies = [m["text"] for m in msgs if m["role"] == "assistant"]
    if not replies:
        _refuse("nothing to copy yet")
        return thread
    if n > len(replies):
        _refuse("only %d repl%s -- /copy %d is the oldest"
                % (len(replies), "y" if len(replies) == 1 else "ies", len(replies)))
        return thread
    tool = clipboard()
    if tool is None:
        _refuse("no clipboard here -- /save writes a file")
        return thread
    # no control character leaves (ESC[201~ would end a bracketed paste
    # early); tabs and newlines stay
    text = textmod.scrub(replies[-n])
    try:
        rc = subprocess.run(tool, input=text.encode("utf-8"), stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, timeout=5).returncode
    except (OSError, subprocess.SubprocessError):
        rc = -1
    if rc != 0:
        _refuse("the clipboard (%s) failed -- /save writes a file" % tool[0])
        return thread
    what = "the last reply" if n == 1 else "reply %d from the end" % n
    _tell("copied %s (%d characters)" % (what, len(text)))
    return thread


def transcript(msgs, name="spark"):
    """The conversation as plain text: `you: ` or `<name>: ` before each
    message, a blank line between them."""
    return "\n\n".join("%s: %s" % ("you" if m["role"] == "user" else name, m["text"].strip())
                       for m in msgs) + "\n"


def _create(path):
    """A new file at `path`, 0600, never over one that is there: a
    writable file object, or FileExistsError."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.fchmod(fd, 0o600)
    return os.fdopen(fd, "w", encoding="utf-8")


def save_names(typed=""):
    """Where /save may write, in order: the name as typed; a directory
    (one that is there, or a name ending in /) holds the default name;
    the default is ~/spark-chat-DATE.txt, then -2 .. -99."""
    stem = time.strftime("spark-chat-%Y-%m-%d")
    if typed:
        path = os.path.abspath(os.path.expanduser(typed))
        if not (typed.endswith("/") or os.path.isdir(path)):
            return [path]
        base = os.path.join(path, stem)
    else:
        base = os.path.join(os.path.expanduser("~"), stem)
    return [base + ".txt"] + ["%s-%d.txt" % (base, i) for i in range(2, SAVE_MAX + 1)]


def _slash_save(cfg, thread, args):
    # the thread stays sealed; the file is the person's own export, in
    # plain text, where they said -- never over a file that is there
    from . import cli, look
    msgs = _turns(cfg, thread, "/save")
    if msgs is None:
        return thread
    body = textmod.scrub(transcript(msgs, cfg.name if look.awake() else "spark"))
    names = save_names(" ".join(args))
    for path in names:
        try:
            with _create(path) as f:
                f.write(body)
            break
        except FileExistsError:
            continue
        except OSError as e:
            _refuse("%s: %s" % (cli._short(path), e.strerror or e))
            return thread
    else:
        _refuse("%s is already there -- /save FILE names another" % cli._short(names[0]))
        return thread
    turns = sum(1 for m in msgs if m["role"] == "user")
    _tell("saved to %s (%d turn%s)" % (cli._short(path), turns, "" if turns == 1 else "s"))
    return thread


class _Kept:
    """The stream under /read's gate: every kept line into the chat's
    wrap, the pulse stopped at the first, the text kept for the thread.
    The last newline is held back, so the wrap's own close ends the
    reply as a streamed one ends."""

    def __init__(self, wrap, busy):
        self.wrap, self.busy = wrap, busy
        self.text = []
        self.owed = False

    def write(self, s):
        if not s:
            return
        self.busy.stop()
        self.text.append(s)
        if self.owed:
            s, self.owed = "\n" + s, False
        if s.endswith("\n"):
            s, self.owed = s[:-1], True
        if s:
            self.wrap.feed(s)

    def flush(self):
        self.wrap.stream.flush()


def _slash_read(cfg, thread, args):
    # contract 11 inside the chat: the file is the source, and read.answer
    # is the one law (held back, parts, the reading, the gate, the
    # opening-words refusal); the kept lines are the reply and the
    # exchange lands on this chat's thread like any turn
    from . import read as readmod, reveal, wire
    want, rest = None, list(args)
    if "--part" in rest:
        i = rest.index("--part")
        want = int(rest[i + 1]) if rest[i + 1:i + 2] and number(rest[i + 1]) else 0
        del rest[i:i + 2]
        if want < 1:
            _refuse("--part takes a number, 1 or more")
            return thread
    words, paths = refs(rest)
    if len(paths) != 1:
        _refuse("/read takes one file: /read @FILE [question]")
        return thread
    try:
        data = file_text(paths[0], os.getcwd())
    except RefError as e:
        _refuse(e.hint)
        return thread
    if not data.strip():
        _refuse("@%s is empty" % paths[0])
        return thread
    cps = reveal.auto_cps(cfg) if REVEAL[0] == "auto" else REVEAL[0]
    wrap = textmod.Wrap(sys.stdout, cps=cps)
    busy = textmod.Busy(sys.stderr)
    out = _Kept(wrap, busy)
    if thread is None:
        thread = new_thread(cfg)      # made first: the turn record names it, so /last shows this turn
    try:
        readmod.answer(cfg, data, " ".join(words), out, want, on_ask=busy.start, thread=thread)
    except (readmod.Refused, wire.BrainError) as e:
        busy.stop()
        if wrap.started:
            wrap.close()
        _refuse(e.hint)
        return thread
    except KeyboardInterrupt:
        busy.stop()
        if wrap.started:
            wrap.close()
        _tell("stopped")
        return thread
    finally:
        busy.stop()
    wrap.close()
    return _land(cfg, thread, ("/read " + " ".join(args)).strip(), "".join(out.text).rstrip("\n"),
                 {"mode": "read", "cwd": os.getcwd()}, {"kind": "read"})


def _slash_do(cfg, thread, args):
    # the goal goes to spark do's own terminal driver, in this terminal:
    # each step confirmed (the sandbox: its review and the typed yes);
    # the chat gains no power of its own, and comes back after
    import signal
    from . import do as domod, say
    boxed = args[:1] == ["--sandbox"]
    goal = args[1:] if boxed else list(args)
    if not goal:
        _refuse("/do takes a goal: /do GOAL")
        return thread
    term = signal.getsignal(signal.SIGTERM)
    domod.END[0] = None
    said = "the run did not start"
    try:
        domod.cmd_do((["--sandbox"] if boxed else []) + ["--"] + goal)
    except SystemExit as e:
        if e.code == 143:
            raise               # SIGTERM ends the chat too
    except KeyboardInterrupt:
        say()
        said = "stopped"
    finally:
        signal.signal(signal.SIGTERM, term)
    if domod.END[0]:
        said = "%s -- %s" % domod.END[0][:2]
    # the run made its own thread; the exchange lands on the chat's after
    # it, so the chat's stays the newest (`??` and the next spark chat go
    # on with the chat), and /save and /copy see it
    thread = _land(cfg, thread, " ".join(["/do"] + list(args)), said, {"mode": "do", "cwd": os.getcwd()}, {"kind": "do"})
    _tell("back in the chat")
    return thread


SLASH_VERBS = {"/help": _slash_help, "/new": _slash_new, "/resume": _slash_resume, "/reveal": _slash_reveal,
               "/clear": _slash_clear, "/keep": _slash_keep, "/last": _slash_last, "/model": _slash_model,
               "/copy": _slash_copy, "/save": _slash_save, "/read": _slash_read, "/do": _slash_do,
               "/aloud": _slash_aloud, "/again": _slash_again}


class _Keys:
    """The chat's own keys at `chat>` (a terminal only):

      Esc alone, on an EMPTY line, ends the chat exactly as Ctrl-D does.
      An Esc counts as alone only when nothing follows it within the
      key-sequence wait (readline's keyseq-timeout, 500 ms by default),
      so the arrows, Alt-b and Esc v still arrive whole. With text on
      the line a lone Esc is dropped under GNU readline (the next key is
      never taken as Alt-key), and the words stay -- but in a search,
      where Esc ends it, and in vi mode, where Esc is the command mode.
      Esc v listens (_hear): the words land on the line; Enter sends.
      Esc x stops the speaking (_hush).

    GNU readline (Linux): Python runs it in callback mode, where a
    binding for a lone Esc never fires -- the key-sequence wait is not
    applied there. So a getc hook (ctypes over rl_getc_function) sees
    each key first: a lone Esc on an empty line, outside a search,
    becomes the terminal's EOF character, readline's own Ctrl-D; Esc v
    and Esc x are taken there on any line, and the line is redrawn
    (C-x C-], bound to redraw-current-line). A Ctrl-C during the wait
    is the chat's Ctrl-C: it is sent again to the main thread once the
    hook has returned (a ctypes callback cannot raise), so input()
    raises KeyboardInterrupt as at any other moment. libedit (Apple's
    python3), or no hook: the first key on an EMPTY line is read raw
    before input() -- a lone Esc ends, Esc v and Esc x are taken, and
    anything else goes back into the terminal's input queue (TIOCSTI)
    for readline to read as typed. With text on a libedit line, Esc is
    libedit's own: its rl_getc_function is read once, when readline
    starts, so no hook can see a key after that -- a lone Esc there
    stays libedit's Alt prefix for the next key."""

    RL_SEARCHING = 0x780        # RL_STATE_ISEARCH|NSEARCH|SEARCH|NUMERICARG
    REDRAW = r'"\C-x\C-]": redraw-current-line'

    def __init__(self, readline):
        self.rl = readline
        self.fd = sys.stdin.fileno()
        self.wait = 0.5
        self.active = False
        self.how = "raw"
        self.hook = None
        if readline is not None and "libedit" not in (readline.__doc__ or ""):
            try:
                self._gnu()
                self.how = "gnu"
            except Exception:       # noqa: BLE001 -- no hook: the raw read on an empty line
                self.hook = None

    # ------------------------------------------------------------ GNU
    def _gnu(self):
        import ctypes
        import termios
        lib = ctypes.CDLL(self.rl.__file__)
        getc = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p)
        ptr = ctypes.c_void_p.in_dll(lib, "rl_getc_function")
        if not ptr.value:
            raise OSError("no rl_getc_function")
        self.orig_ptr = ptr.value
        self.orig = getc(ptr.value)
        self.end = ctypes.c_int.in_dll(lib, "rl_end")
        self.point = ctypes.c_int.in_dll(lib, "rl_point")
        self.state = ctypes.c_ulong.in_dll(lib, "rl_readline_state")
        try:
            self.mode = ctypes.c_int.in_dll(lib, "rl_editing_mode")     # 0 vi, 1 emacs
        except ValueError:
            self.mode = None
        self.stuff = lib.rl_stuff_char
        self.stuff.argtypes = [ctypes.c_int]
        try:
            lib.rl_variable_value.restype = ctypes.c_char_p
            lib.rl_variable_value.argtypes = [ctypes.c_char_p]
            ms = int(lib.rl_variable_value(b"keyseq-timeout") or 500)
            self.wait = ms / 1000.0 if ms > 0 else 0.5
        except (AttributeError, ValueError, TypeError):
            pass
        eof = termios.tcgetattr(self.fd)[6][termios.VEOF]
        self.eof = eof if isinstance(eof, int) else ord(eof)
        self.rl.parse_and_bind(self.REDRAW)
        self.hook = getc(self._getc)        # kept: the pointer must outlive the call
        self.ptr = ptr
        ptr.value = ctypes.cast(self.hook, ctypes.c_void_p).value

    def _getc(self, stream):
        c = self.orig(stream)
        try:
            _face_rest()                        # a key typed: the face rests
        except Exception:   # noqa: BLE001 -- a key is never lost to the face
            pass
        if c != 27 or not self.active:
            return c
        try:
            import select
            if select.select([self.fd], [], [], self.wait)[0]:
                nxt = os.read(self.fd, 1)
                if nxt == b"v":
                    return self._gnu_listen()
                if nxt == b"x":
                    _hush()
                    return self._redraw()
                if nxt:
                    self.stuff(nxt[0])
                return 27
            if self.state.value & self.RL_SEARCHING:
                return 27                       # Esc ends a search
            if self.end.value == 0:
                return self.eof                 # a lone Esc on an empty line: Ctrl-D
            if self.mode is not None and self.mode.value == 0:
                return 27                       # vi mode: Esc is the command mode
            return self._redraw()              # a lone Esc on a line: dropped, never Alt for the next key
        except KeyboardInterrupt:
            self._interrupt()                   # Ctrl-C in the wait: the chat's Ctrl-C, once this returns
            return self._redraw()
        except SystemExit as e:
            _ended(e)                           # a hangup while it listened: the mic is off; end as the signal would
        except Exception:   # noqa: BLE001 -- a key is never lost to the hook
            pass
        return 27

    @staticmethod
    def _interrupt():
        """SIGINT again, to the main thread, a moment after the hook has
        returned to readline's wait: input() then raises KeyboardInterrupt."""
        import signal
        import threading
        main = threading.main_thread().ident
        t = threading.Timer(0.05, signal.pthread_kill, (main, signal.SIGINT))
        t.daemon = True
        t.start()

    def _redraw(self):
        self.stuff(0x1d)
        return 0x18

    def _gnu_listen(self):
        os.write(1, ("\r\x1b[2K" + _listening()).encode("utf-8", "replace"))
        text, why = _hear()
        os.write(1, b"\r\x1b[2K")
        if text:
            line, at = self.rl.get_line_buffer(), self.point.value
            self.rl.insert_text((" " if line and at and not line[at - 1].isspace() else "") + text)
        elif why:
            os.write(1, (why + "\r\n").encode("utf-8", "replace"))
        return self._redraw()

    def close(self):
        if self.hook is not None:
            self.ptr.value = self.orig_ptr
            self.hook = None

    # ------------------------------------------------------------ raw
    def _push(self, data):
        """Bytes back into the terminal's input queue, as if typed."""
        import fcntl
        import termios
        for b in data:
            fcntl.ioctl(self.fd, termios.TIOCSTI, bytes([b]))

    def _raw(self, prompt):
        """The first key on an empty line, read before input(): EOFError
        for a lone Esc (and Ctrl-D); Esc v and Esc x taken; anything else
        pushed back for readline."""
        import select
        import termios
        shown = prompt.replace("\001", "").replace("\002", "")
        old = termios.tcgetattr(self.fd)
        raw = termios.tcgetattr(self.fd)
        raw[3] &= ~(termios.ICANON | termios.ECHO)
        raw[6][termios.VMIN], raw[6][termios.VTIME] = 1, 0
        first = True
        while True:
            # raw before the prompt shows: a key typed the moment it
            # appears is neither echoed nor held for a line
            termios.tcsetattr(self.fd, termios.TCSANOW, raw)
            if first:
                sys.stdout.write(shown)
                sys.stdout.flush()
                first = False
            try:
                select.select([self.fd], [], [])
                got = os.read(self.fd, 1024)
                _face_rest()                    # a key typed: the face rests
                if got == b"\x1b":
                    if not select.select([self.fd], [], [], self.wait)[0]:
                        raise EOFError          # a lone Esc: as Ctrl-D
                    got += os.read(self.fd, 1024)
                if got == b"\x04":
                    raise EOFError
                while select.select([self.fd], [], [], 0)[0]:
                    more = os.read(self.fd, 1024)
                    if not more:
                        break
                    got += more
                if got == b"\x1bx":
                    _hush()
                    continue
                if got == b"\x1bv":
                    sys.stdout.write("\r\x1b[2K" + _listening())
                    sys.stdout.flush()
                    text, why = _hear()
                    sys.stdout.write("\r\x1b[2K")
                    if not text:
                        sys.stdout.write((why + "\r\n" if why else "") + shown)
                        sys.stdout.flush()
                        continue
                    got = text.encode("utf-8", "replace")
                try:
                    self._push(got)
                except OSError:
                    # no TIOCSTI here: what was typed lands through the
                    # startup hook when it is text, and the keys are
                    # readline's own from now on
                    self.how = None
                    typed = got.decode("utf-8", "replace")
                    if self.rl is not None and typed.isprintable():
                        self.rl.set_startup_hook(lambda: (self.rl.insert_text(typed), self.rl.set_startup_hook(None)))
                sys.stdout.write("\r")
                sys.stdout.flush()
                return
            finally:
                termios.tcsetattr(self.fd, termios.TCSANOW, old)

    # ------------------------------------------------------------ both
    def read(self, prompt):
        """input(prompt) with the chat's keys."""
        if self.how == "raw":
            self._raw(prompt)
        self.active = True
        try:
            return input(prompt)
        finally:
            self.active = False


@contextmanager
def _prompts_only(readline):
    """The chat's readline history keeps the chat's own prompts: the
    lines a verb read with input() inside (spark do's Enter, its yes, an
    edit) are taken out again, so the sealed history never holds them."""
    n = readline.get_current_history_length() if readline else 0
    try:
        yield
    finally:
        if readline:
            for i in range(readline.get_current_history_length() - 1, n - 1, -1):
                try:
                    readline.remove_history_item(i)     # 0-based, GNU and libedit alike
                except ValueError:
                    break


def cmd_chat(args):
    from . import MARK, config, say, wire
    from . import cli
    if args and args[0] in ("-h", "--help", "help"):
        say(CHAT_USAGE.rstrip() % MARK)
        return 0
    del SAID[:]
    picked = None
    args, cps = cli.reveal_flag(args)
    REVEAL[0] = cps
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
            say("%s chat -- no thread %s: spark history lists them" % (MARK, picked))
            return 2
    else:
        # `more`: go on with the newest -- with history off, the newest
        # kept thread, the one kind a turn still lands on
        thread = last_thread(kept_only=cfg.history <= 0)
    if args:
        words, paths = refs(args)
        return cli._stream("chat", " ".join(words), paths, thread=thread, cps=REVEAL[0])
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
        _voice_setup(cfg, tty)
        # piped, stdout carries the replies alone: no opening, no prompt
        _opening(cfg, thread)
    else:
        _voice_setup(cfg, False)
    prompt = (paint("chat>", "accent", sys.stdout, readline=True) + " ") if tty else ""
    keys = _Keys(readline) if tty else None
    try:
        while True:
            try:
                if sys.stdin.isatty():
                    try:
                        import termios
                        termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
                    except Exception:
                        pass    # scrolled-in escape codes must not become input
                # the prompt in the accent at a tty (readline-bracketed
                # escapes; the plain text stays exactly `chat> `)
                try:
                    text = keys.read(prompt) if keys else input(prompt)
                finally:
                    _face_rest()
            except EOFError:
                if tty:
                    say()
                break
            except KeyboardInterrupt:
                # Ctrl-C at the prompt clears the line, as a shell does:
                # a fresh `chat> `; Ctrl-D and /q end the chat. Piped,
                # an interrupt still ends it (nobody is at a prompt)
                if tty:
                    say()
                    continue
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
                # /save takes the rest of the line as typed: a name may hold spaces
                rest = [text[len(verb):].strip()] if verb == "/save" and parts[1:] else parts[1:]
                if fn:
                    heard = len(SAID)
                    with _prompts_only(readline if verb == "/do" else None):
                        thread = fn(cfg, thread, rest)
                    if verb == "/read" and VOICE["aloud"] and len(SAID) > heard:
                        _aloud_reply(SAID[-1]["text"])
                else:
                    _refuse("no command %s -- /help lists them" % verb)
                if verb != "/clear":
                    say()      # a blank line between turns; /clear starts clean
                continue
            words, paths = refs(text.split())
            # a reply read aloud: its text follows the voice (the reveal
            # on, here), else the voice follows the text as it is shown
            spoken = _spoken()
            try:
                thread = cli.stream_turn(cfg, "chat", " ".join(words), paths, thread=thread, cps=REVEAL[0],
                                         said=SAID, voice=spoken)
            except (RefError, wire.BrainError) as e:
                _face_rest()
                _refuse(e.hint)
            except KeyboardInterrupt as e:
                _face_rest()
                if spoken and VOICE["reader"] is not None:
                    VOICE["reader"].cut()       # the reply stopped, and its voice with it
                thread = getattr(e, "thread", thread)
                say()
                _tell("stopped")
            if FACE[0] is not None:
                FACE[0].line()  # the blank line, counted: the face still finds its row
            else:
                say()          # a blank line between turns
    finally:
        _face_rest()
        if keys:
            keys.close()
        if readline and hist_on:
            _write_chat_history(readline)
    return 0
