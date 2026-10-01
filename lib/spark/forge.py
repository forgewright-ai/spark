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
                print("spark chat: the chat history does not open -- kept as it is; spark user login again",
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
CHAT_USAGE = """%s chat -- a conversation

  spark chat <words>             one more turn on the newest thread, streamed
  spark chat --thread N [words]  an older thread instead: N from the /resume
                                 or spark history list (1 = newest), or a
                                 literal thread id
  spark chat                     a conversation at the `chat> ` prompt; it
                                 goes on with the newest thread and says so
  spark chat --reveal [N|auto|off]
                                 the pace of a reply at a terminal: N
                                 characters a second, auto (the measured
                                 threshold: under the model's own speed,
                                 a reader's 40 at most), off (as the chunks
                                 come, the default); /reveal inside shows
                                 the numbers, /reveal N|auto|off sets it;
                                 SPARK_REVEAL in spark.env is the standing
                                 choice

  Inside it: @FILE words asks about a file; /help lists the verbs (/new,
  /resume, /clear, /keep, /last, /model, /reveal, /copy, /save, /read,
  /do); /q (or /quit, /exit, :q, quit, exit, bye, Ctrl-D) ends it, with a
  goodbye on an awakened machine; Ctrl-C clears the line at the prompt and
  cancels a reply in progress, and neither ends the chat. Every turn is
  kept as a thread (spark history) for SPARK_HISTORY days; /keep keeps
  this one past that and past
  spark clear --history, and /keep off lets it go.

  /copy puts a reply on the clipboard, /save writes the conversation to a
  file, /read @FILE answers from the file and only from it, and /do GOAL
  runs spark do here, each step confirmed.
"""

# Any of these alone ends the conversation. Generous on purpose: a quit
# word the REPL does not know goes to the model, which role-plays an
# exit while the prompt lives on -- a first-session trap.
QUIT_WORDS = ("/q", "/quit", "/exit", ":q", ":quit", ":wq", "quit", "exit", "bye")

# The awakened chat (look.active("words") at a terminal): the face leads
# each reply and each of the chat's own lines, a refusal is the puzzled
# face on stdout instead of `spark: <hint>` on stderr, and the end says
# goodbye. Unawakened (or piped) it stays False and every byte is today's.
LIVING = [False]
# This chat's own turns since it began (or since /new), in memory only:
# what /copy and /save take when no thread keeps them (SPARK_HISTORY=0)
# -- the replies on the screen this session, gone when the chat ends.
SAID = []
CONTINUING_COLS = 79    # the continuing line fits 80 columns
SAVE_MAX = 99           # ~/spark-chat-DATE.txt, then -2 .. -99


def _face(mood):
    """The machine's face for `mood`, in the accent (plain when piped)."""
    from . import words
    return paint(words.face(mood), "accent")


def _tell(line, mood="idle"):
    """One line of the chat's own: face-led when awake, plain otherwise."""
    from . import say
    say(_face(mood) + " " + line if LIVING[0] else line)


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


def _refuse(hint, head=""):
    """A refusal inside the chat: `spark: <hint>` on stderr, as always;
    awake, the puzzled face and the hint as a whole sentence on stdout
    (`head`, a program's name that opens the hint, keeps its case)."""
    if LIVING[0]:
        from . import cli, say
        say(_face("puzzled") + " " + cli._tidy(hint, head=head))
    else:
        print("spark: " + hint, file=sys.stderr, flush=True)


def ago(ts, now=None):
    """`N min ago`, `N h ago` or `N d ago` for a thread's stamp; '' when
    it does not read."""
    try:
        then = time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M:%S"))
    except (TypeError, ValueError, OverflowError):
        return ""
    secs = max(0, (time.time() if now is None else now) - then)
    if secs < 3600:
        return "%d min ago" % max(1, secs // 60)
    if secs < 86400:
        return "%d h ago" % (secs // 3600)
    return "%d d ago" % (secs // 86400)


def continuing(msgs, now=None):
    """The line that says this chat goes on with a thread: its first user
    message's first words, cut at a word to fit 80 columns, and how long
    ago it was last written. '' for a thread with no user message."""
    from . import glyph
    first = next((m for m in msgs if m.get("role") == "user"), None)
    if first is None:
        return ""
    when = ago(msgs[-1].get("ts", ""), now)
    head, tail = '  continuing "', '"%s -- /new starts fresh' % (" (%s)" % when if when else "")
    room = CONTINUING_COLS - len(head) - textmod.cols(tail)
    words = " ".join(textmod.scrub(first.get("text", "")).split())
    if textmod.cols(words) > room:      # columns, not characters: a wide one takes two
        cut = glyph("cut")
        words = textmod.cut_cols(words, room - textmod.cols(cut))
        if " " in words:
            words = words[:words.rfind(" ")]
        words = words.rstrip() + cut
    return head + words + tail


def _opening(thread):
    """The chat's first lines at a terminal. Awake: the face and a greet
    line, the continuing line, the hint (muted). Unawakened: today's
    banner and the continuing line."""
    from . import glyph, say, words
    cont = continuing(load(thread)) if thread else ""
    if LIVING[0]:
        say(paint(glyph("hammer") + " " + words.face("idle"), "accent") + " " + words.greeting())
        if cont:
            say(cont)
        say(paint("  /help lists the commands; Ctrl-D ends", "muted"))
        return
    say("chat -- /help, Ctrl-D or /q ends")
    if cont:
        say(cont)


def _goodbye():
    """Awake, the end of the chat: the pleased face and the done line."""
    from . import words
    if LIVING[0]:
        _tell(words.load().get("done") or "That is everything for now.", "pleased")


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


def _slash_help(cfg, thread, args):
    from . import say
    say("/help    this list")
    say("/new     a fresh thread")
    say("/resume  an older thread: bare lists the newest 5, /resume N picks")
    say("/clear   wipe the screen; the thread goes on")
    say("/keep    keep this thread past SPARK_HISTORY; /keep off lets it go")
    say("/last    the last turn, with its tok/s")
    say("/model   which model is answering")
    say("/reveal  bare: the model's measured pace and the threshold under it;")
    say("         N | auto | off sets the pace of the replies (off = as they come)")
    say("/copy    the last reply to the clipboard; /copy N the Nth from the end")
    say("/save    the conversation to ~/spark-chat-DATE.txt, or /save FILE")
    say("/read    /read @FILE [question]: an answer that quotes the file")
    say("/do      /do GOAL: spark do here, each step confirmed; /do --sandbox GOAL")
    say("/q       end the conversation (Ctrl-D works too)")
    return thread


def _slash_new(cfg, thread, args):
    from . import MARK, say
    say("%s: a fresh thread" % MARK)
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
            say("(no threads yet)")
        for i, th in enumerate(threads, 1):
            say("%d) %d turn%s  %s" % (i, th["turns"], "" if th["turns"] == 1 else "s", th["title"]))
        return thread
    tid = resolve_thread(args[0], threads)
    if not tid:
        _refuse("no thread %s -- /resume lists them" % args[0])
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


def _slash_keep(cfg, thread, args):
    # /keep moves the current thread into kept/ (pruning and a clear never
    # look there), /keep off moves it back to age like any other. The
    # thread goes on either way: only where its file lives changes.
    from . import say
    if args not in ([], ["off"]):
        _refuse("/keep takes nothing, or off")
        return thread
    if not thread:
        if cfg.history <= 0:
            _refuse("history is off (SPARK_HISTORY) and nothing is kept, so this chat has no thread to keep")
        else:
            _refuse("this chat has no thread yet, and its first turn makes the one /keep keeps")
        return thread
    try:
        if args == ["off"]:
            if unkeep(thread):
                say("let go: this thread lives SPARK_HISTORY days like any other")
            else:
                say("this thread is not kept, so there is nothing to let go")
            return thread
        keep(thread)
    except KeepError as e:
        _refuse(e.hint)
        return thread
    say("kept: this thread stays past SPARK_HISTORY and spark clear --history")
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
        _refuse(e.hint)
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
REVEAL = [0]           # the chat's pace: 0 (as the chunks come, the default) | auto | N (/reveal, --reveal, SPARK_REVEAL)


def _slash_reveal(cfg, thread, args):
    from . import MARK, reveal, say
    if not args:
        # the benchmark: what the model writes, the threshold under it,
        # and what this chat does now -- the choice stays yours
        for ln in reveal.pace_report(cfg, REVEAL[0]):
            say("%s: %s" % (MARK, ln))
        return thread
    word = args[0]
    if word == "off":
        REVEAL[0] = 0
        say("%s: the replies come as they are made" % MARK)
        return thread
    if word == "auto":
        REVEAL[0] = "auto"
        say("%s: the replies at the measured threshold (%d a second now; /reveal shows the numbers)" % (MARK, reveal.auto_cps(cfg)))
        return thread
    try:
        n = int(word)
    except ValueError:
        n = -1
    if not reveal.CPS_MIN <= n <= reveal.CPS_MAX:
        say("%s: /reveal takes a number, %d..%d characters a second, auto, or off" % (MARK, reveal.CPS_MIN, reveal.CPS_MAX))
        return thread
    REVEAL[0] = n
    say("%s: the replies at %d characters a second (/reveal auto or off)" % (MARK, n))
    return thread


def _turns(cfg, thread, verb):
    """The chat's user and assistant messages, oldest first; None, with
    the refusal said, when there are none to take. No thread (history
    off): the turns this chat said since it began or since /new (SAID)."""
    msgs = [m for m in load(thread) if m.get("role") in ("user", "assistant")] if thread else list(SAID)
    if msgs:
        return msgs
    if not thread and cfg.history <= 0:
        _refuse("history is off (SPARK_HISTORY) and this chat has no turns yet, so %s has nothing to take" % verb)
    else:
        _refuse("this chat has no turns yet, so %s has nothing to take" % verb)
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
        _refuse("/copy takes a number: /copy N copies the Nth reply from the end")
        return thread
    n = int(args[0]) if args else 1
    msgs = _turns(cfg, thread, "/copy")
    if msgs is None:
        return thread
    replies = [m["text"] for m in msgs if m["role"] == "assistant"]
    if not replies:
        _refuse("this chat has no reply yet, so /copy has nothing to take")
        return thread
    if n > len(replies):
        _refuse("this chat has %d repl%s: /copy %d is the oldest"
                % (len(replies), "y" if len(replies) == 1 else "ies", len(replies)))
        return thread
    tool = clipboard()
    if tool is None:
        _tell("No clipboard here: /save writes the conversation to a file.", "puzzled")
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
        _refuse("%s did not take the reply -- /save writes the conversation to a file" % tool[0], head=tool[0])
        return thread
    what = "The last reply" if n == 1 else "The reply %d from the end" % n
    _tell("%s is on the clipboard (%d characters)." % (what, len(text)))
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
        _refuse("%s is there already, and /save never writes over a file -- name another: /save FILE"
                % cli._short(names[0]))
        return thread
    turns = sum(1 for m in msgs if m["role"] == "user")
    _tell("Saved to %s (%d turn%s)." % (cli._short(path), turns, "" if turns == 1 else "s"))
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
    from . import glyph, read as readmod, reveal, say, wire
    want, rest = None, list(args)
    if "--part" in rest:
        i = rest.index("--part")
        want = int(rest[i + 1]) if rest[i + 1:i + 2] and number(rest[i + 1]) else 0
        del rest[i:i + 2]
        if want < 1:
            _refuse("--part N is a part number, 1 up")
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
        _refuse("@%s is empty -- there is nothing to read" % paths[0])
        return thread
    cps = reveal.auto_cps(cfg) if REVEAL[0] == "auto" else REVEAL[0]
    wrap = textmod.Wrap(sys.stdout, cps=cps, lead=_face("idle") + " " if LIVING[0] else None)
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
        say("%s (stopped)" % glyph("hammer"))
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
        _refuse("/do takes a goal: /do GOAL, or /do --sandbox GOAL")
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
    _tell("Back in the chat.")
    return thread


SLASH_VERBS = {"/help": _slash_help, "/new": _slash_new, "/resume": _slash_resume, "/reveal": _slash_reveal,
               "/clear": _slash_clear, "/keep": _slash_keep, "/last": _slash_last, "/model": _slash_model,
               "/copy": _slash_copy, "/save": _slash_save, "/read": _slash_read, "/do": _slash_do}


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
    from . import MARK, glyph, config, look, say, wire
    from . import cli
    if args and args[0] in ("-h", "--help", "help"):
        say(CHAT_USAGE.rstrip() % MARK)
        return 0
    LIVING[0] = False
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
            say("%s chat -- no thread %s (spark history lists them)" % (MARK, picked))
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
        try:
            LIVING[0] = look.active("words", sys.stdout)
        except Exception:       # noqa: BLE001 -- a look file is never a reason to fail
            LIVING[0] = False
        # piped, stdout carries the replies alone: no banner, no prompt
        _opening(thread)
    prompt = (paint("chat>", "accent", sys.stdout, readline=True) + " ") if tty else ""
    bye = False
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
                text = input(prompt)
            except EOFError:
                if tty:
                    say()
                bye = True
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
                bye = True
                break
            if text.startswith("/"):
                parts = text.split()
                verb = parts[0]
                fn = SLASH_VERBS.get(verb)
                # /save takes the rest of the line as typed: a name may hold spaces
                rest = [text[len(verb):].strip()] if verb == "/save" and parts[1:] else parts[1:]
                if fn:
                    with _prompts_only(readline if verb == "/do" else None):
                        thread = fn(cfg, thread, rest)
                else:
                    _refuse("no %s -- /help lists them" % verb)
                if verb != "/clear":
                    say()      # a blank line between turns; /clear starts clean
                continue
            words, paths = refs(text.split())
            try:
                thread = cli.stream_turn(cfg, "chat", " ".join(words), paths, thread=thread, cps=REVEAL[0],
                                         lead=_face("idle") + " " if LIVING[0] else None, said=SAID)
            except (RefError, wire.BrainError) as e:
                _refuse(e.hint)
            except KeyboardInterrupt as e:
                thread = getattr(e, "thread", thread)
                say()
                say("%s (stopped)" % glyph("hammer"))
            say()              # a blank line between turns
    finally:
        if readline and hist_on:
            _write_chat_history(readline)
    if bye:
        _goodbye()
    return 0
