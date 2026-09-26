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
    request, wire.BrainError from the request. Any end mid-stream -- a
    KeyboardInterrupt (Ctrl-C at the prompt), a BrokenPipeError /
    ConnectionResetError from on_delta (a page or desktop client pressing
    stop), or a BrainError of kind `cut` (the server died with the answer
    half sent) -- appends the user line and, when any text arrived, the
    partial reply (partial=True), then re-raises; the thread id rides on
    the exception (`e.thread`) so the caller can keep going with it. Every
    other BrainError failed before a byte came back and leaves the thread
    as it was. Nothing is printed here -- that is the caller's job."""
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
  spark chat                     a conversation at the `chat> ` prompt
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
  /resume, /clear, /keep, /last, /model, /reveal); /q (or /quit, /exit, :q,
  quit, exit, bye, Ctrl-D) ends, silently; Ctrl-C cancels a reply in progress
  without ending the chat. Every turn is kept as a thread (spark history) for
  SPARK_HISTORY days; /keep keeps this one past that and past
  spark clear --history, and /keep off lets it go.
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
    say("/keep    keep this thread past SPARK_HISTORY; /keep off lets it go")
    say("/last    the last turn, with its tok/s")
    say("/model   which model is answering")
    say("/reveal  bare: the model's measured pace and the threshold under it;")
    say("         N | auto | off sets the pace of the replies (off = as they come)")
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


def _slash_keep(cfg, thread, args):
    # /keep moves the current thread into kept/ (pruning and a clear never
    # look there), /keep off moves it back to age like any other. The
    # thread goes on either way: only where its file lives changes.
    from . import say
    if args not in ([], ["off"]):
        print("spark: /keep takes nothing, or off", file=sys.stderr, flush=True)
        return thread
    if not thread:
        if cfg.history <= 0:
            print("spark: history is off (SPARK_HISTORY) and nothing is kept, so this chat has no thread to keep",
                  file=sys.stderr, flush=True)
        else:
            print("spark: this chat has no thread yet, and its first turn makes the one /keep keeps",
                  file=sys.stderr, flush=True)
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
        print("spark: " + e.hint, file=sys.stderr, flush=True)
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


SLASH_VERBS = {"/help": _slash_help, "/new": _slash_new, "/resume": _slash_resume, "/reveal": _slash_reveal,
               "/clear": _slash_clear, "/keep": _slash_keep, "/last": _slash_last, "/model": _slash_model}


def cmd_chat(args):
    from . import MARK, glyph, config, say, wire
    from . import cli
    if args and args[0] in ("-h", "--help", "help"):
        say(CHAT_USAGE.rstrip() % MARK)
        return 0
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
    if tty:
        # piped, stdout carries the replies alone: no banner, no prompt
        say("chat -- /help, Ctrl-D or /q ends")
    prompt = (paint("chat>", "accent", sys.stdout, readline=True) + " ") if tty else ""
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
                thread = cli.stream_turn(cfg, "chat", " ".join(words), paths, thread=thread, cps=REVEAL[0])
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
