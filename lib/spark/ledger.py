# spark.ledger -- what you have already weighed, kept per name, sealed in
# the account's store (users/<name>/ledger), written only by you. One
# file, one record shape ({kind, name, ts, note}); the rule that decides
# when a record stops counting belongs to the contract that wrote it, and
# nowhere else. A rule that generalised would fit none of them:
#
#   kind   what one record is        what invalidates it       what it does
#   edit   a note you declined in    its first quoted span     keeps the note
#          the editor (contract 10)  left the text             out of the next ?
#   ask    a question you answered   nothing but age and       keeps the question
#          (contract 12)             `ledger clear`: a plan    from being asked
#                                    moves, an answer stays    again
#   read   a question asked of a     nothing: a source does    a record to read
#          source (contract 11)      not change                (no suppression)
#   drill  an item and when it is    never: a schedule that    brings the item
#          next due (contract 13)    expires is not one        back when due
#
# So `edit` retires a note by content and `drill` must not age at all;
# every kind shares the caps and the sealed file, nothing else.
#
#   spark edit --ledger [clear] --name NAME   the editor's, in its pane
#   spark ask  --ledger [clear] --name NAME   the questions answered
#   spark read --ledger [clear] [--name NAME] the questions asked of a source

import fcntl
import hashlib
import json
import os
import re
import shutil
import time
from contextlib import contextmanager

from . import MARK, STATE_DIR, config, log_exc, say, vault
from . import text as textmod

NOTE_MAX = 300        # characters kept of one note
PER_NAME = 30         # notes per name and kind; the oldest goes
TOTAL_MAX = 200       # notes in all
SEND_MAX = 1200       # characters a request carries, newest first

KIND_EDIT, KIND_ASK, KIND_READ, KIND_DRILL = "edit", "ask", "read", "drill"
KIND_FAIL = "fail"
# The table above, as the code reads it. `age`: SPARK_HISTORY days apply.
# `retire`: what drops a record before its time -- "quote" is contract
# 10's (the note's first quoted span left the text), "never" is every
# other contract's, each for its own stated reason.
RULES = {
    KIND_EDIT: {"age": True, "retire": "quote"},
    KIND_ASK: {"age": True, "retire": "never"},
    KIND_READ: {"age": True, "retire": "never"},
    KIND_DRILL: {"age": False, "retire": "never"},
    # failure memory: the shape of a failure maps to the fix that worked;
    # a fix whose head word left PATH retires -- a remedy naming a tool
    # that is gone is noise, not memory
    KIND_FAIL: {"age": True, "retire": "path"},
}
FAILS_INDEX = os.path.join(STATE_DIR, "fails")           # hash head rc fix -- the hook reads it
FAIL_PENDING = os.path.join(STATE_DIR, "fail-pending")   # shape head rc -- explain writes it
# a fix line can carry a secret (`export TOKEN=... && curl`): in the plain
# index every NAME=value whose NAME smells of one becomes NAME=... -- the
# sealed ledger keeps the line whole
SECRET_RE = re.compile(r"(?i)\b(\w*(?:pass|pwd|token|secret|key|auth)\w*)=(?:\"[^\"]*\"|'[^']*'|\S+)")
# what a writer says of a file it cannot read: never written over
NO_OPEN = "the ledger does not open -- spark user login again"


def _name(name):
    """A record's name: the basename, strict UTF-8 -- a title that arrived
    with a byte that was not UTF-8 (a lone surrogate from argv) is the
    same name every time, and never a crash at the store's encode."""
    return os.path.basename(textmod.utf8((name or "").strip()))


def _kind(e):
    """A record's kind; one written before v1.15 is the editor's."""
    return e.get("kind") or KIND_EDIT



class Refused(Exception):
    def __init__(self, hint):
        super().__init__(hint)
        self.hint = hint


def _store():
    """(sealed path, dk, name) of this machine's own account, or None."""
    from . import users
    name, _ = users.account()
    if name and users.exists(name):
        dk = users.account_key()
        if dk:
            return os.path.join(users.user_dir(name), "ledger"), dk, name
    return None


@contextmanager
def _locked():
    """An exclusive flock on `.lock` beside the sealed file, around every
    load-mutate-save (the serve.lock pattern in engine.py): two editor
    panes declining at once must both survive, and a `?` writes on the
    read path when a note aged. Blocking on purpose -- the hold is
    milliseconds. No account yet means nobody to race with: the first
    write provisions the store under the caller's own feet."""
    from . import users
    name = users.account()[0]
    if not name:
        yield
        return
    users.make_dirs(name)
    fd = os.open(os.path.join(users.user_dir(name), "ledger.lock"), os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _load(st=None, strict=False):
    """The records. No file is an empty ledger; a file that does not open
    (a flipped byte, a stale account-key) reads as empty too -- except to
    a writer (`strict`), which is refused: a load-mutate-save over it
    would turn the whole ledger into its one new record."""
    st = st or _store()
    if not st or not os.path.isfile(st[0]):
        return []
    try:
        recs = vault.read_sealed(st[0], st[1], "ledger", st[2])
    except (OSError, vault.SealError):
        if strict:
            raise Refused(NO_OPEN)
        return []
    out = []
    for line in (recs[0].decode("utf-8", "replace").splitlines() if recs else []):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("name") and isinstance(d.get("note"), str):
            out.append(d)
    return out


def _save(entries, st=None):
    from . import forge, users
    st = st or _store()
    if st is None:
        forge.local_store(provision=True)
        st = _store()
    if st is None:
        log_exc("ledger store")
        raise OSError("no account to hold the ledger -- a client logs in first: spark user login NAME")
    path, dk, name = st
    users.make_dirs(name)
    vault.write_sealed(path, dk, "ledger", name,
                       "".join(json.dumps(textmod.clean(e), ensure_ascii=False) + "\n" for e in entries).encode("utf-8"))


def _fresh(entries, cfg):
    """Without the notes older than SPARK_HISTORY days -- of the kinds
    whose rule says age applies. A drill schedule does not expire."""
    days = cfg.history if cfg is not None else 30
    if days <= 0:
        return entries
    cutoff = time.time() - days * 86400
    out = []
    for e in entries:
        if not RULES.get(_kind(e), RULES[KIND_EDIT])["age"]:
            out.append(e)
            continue
        try:
            ts = time.mktime(time.strptime(e.get("ts", ""), "%Y-%m-%d %H:%M:%S"))
        except (ValueError, OverflowError):
            ts = 0
        if ts >= cutoff:
            out.append(e)
    return out


def path():
    """Where the ledger is on this machine, or "" with no login. Unlike
    _store() this needs no key: the check row must be able to look at the
    file it cannot open."""
    from . import users
    name = users.account()[0]
    return os.path.join(users.user_dir(name), "ledger") if name else ""


def counts():
    """{kind: how many records} -- what the check row reports. Empty when
    this machine holds no key to its own store."""
    out = {}
    for e in _load():
        out[_kind(e)] = out.get(_kind(e), 0) + 1
    return out


def keep(kind, name, note, cfg=None, missing=""):
    """Keep one record of `kind` under a name; returns it as kept. The
    caps are the file's, shared by every kind; what the record means, and
    when it stops meaning it, is the contract's (RULES above)."""
    name = _name(name)
    text = textmod.utf8(" ".join((note or "").split()))
    if not name:
        raise Refused(missing or "a declined note needs --name NAME (the file's name)")
    if not text:
        raise Refused("nothing to keep -- the note comes on stdin")
    text = text[:NOTE_MAX]
    with _locked():
        entries = _fresh(_load(strict=True), cfg)
        entries = [e for e in entries if not (_kind(e) == kind and e["name"] == name and e["note"] == text)]
        entries.append({"kind": kind, "name": name, "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "note": text})
        mine = [e for e in entries if _kind(e) == kind and e["name"] == name]
        if len(mine) > PER_NAME:
            drop = mine[:len(mine) - PER_NAME]
            entries = [e for e in entries if e not in drop]
        if len(entries) > TOTAL_MAX:
            entries = entries[len(entries) - TOTAL_MAX:]
        _save(entries)
    return text


def decline(name, note, cfg=None):
    """Contract 10's: one note declined in the editor, under a file name."""
    return keep(KIND_EDIT, name, note, cfg)


def entries(name=None, kind=KIND_EDIT):
    """The kept records of one kind, oldest first; one name's when given."""
    name = _name(name) if name else None
    return [e for e in _load() if _kind(e) == kind and (not name or e["name"] == name)]


def _retired(e, retire, data):
    """This kind's own invalidation: `quote` -- the note's first quoted
    span left the text; `path` -- the fix's head word left PATH."""
    from . import text as textmod
    if retire == "quote" and data is not None:
        qs = textmod.quotes(e["note"])
        return bool(qs) and not textmod.anchor(qs[0][0], data)
    if retire == "path":
        head = (e.get("note") or "").split()
        return bool(head) and "/" not in head[0] and shutil.which(head[0]) is None
    return False


def _mine(cfg, kind, name, data=None):
    """(the kind's records for `name`, newest last; every record kept) --
    with this kind's own invalidation applied. `retire: "quote"` needs
    `data`, the text as it is now: a note whose first quoted span has
    left it is dropped from the file here and not sent."""
    retire = RULES.get(kind, RULES[KIND_EDIT])["retire"]
    alive, mine = [], []
    for e in _fresh(_load(), cfg):
        if _kind(e) == kind and e["name"] == name:
            if _retired(e, retire, data):
                continue                     # retired by its own rule
            mine.append(e)
        alive.append(e)
    return mine, alive


# ---------------------------------------------------------- failure memory
def fail_shape(command, rc, first_err):
    """The shape of a failure: sha256(head word, exit code, first stderr
    line folded)[:16]. The head word is the command's own, past sudo/env/
    nohup, so `sudo make` and `make` share a shape."""
    from . import text as textmod
    words = (command or "").split()
    while words and words[0] in ("sudo", "env", "nohup"):
        words = words[1:]
    head = os.path.basename(words[0]) if words else ""
    key = "%s\x00%s\x00%s" % (head, rc, textmod.fold(first_err or ""))
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16], head


def fail_pending(command, rc, first_err):
    """explain's half: remember the failure's shape until a fix works
    (state/fail-pending, one line, 0600). Quiet on any trouble."""
    try:
        from . import state_dir
        state_dir()
        shape, head = fail_shape(command, rc, first_err)
        if not head:
            return
        fd = os.open(FAIL_PENDING, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("%s %s %s\n" % (shape, head, rc))
    except OSError:
        log_exc("fail pending")


def fail_fix(fix, cfg=None):
    """The accepted fix for the pending failure: kept as kind `fail`
    (keyed by shape, count incremented) and the plain index the prompt
    hook reads (state/fails: `hash head rc fix`) rewritten. Quiet when
    nothing is pending -- a fix with no failure is not a record."""
    fix = " ".join((fix or "").split())[:NOTE_MAX]
    try:
        with open(FAIL_PENDING, encoding="utf-8") as f:
            parts = f.read().split()
    except OSError:
        return 0
    if len(parts) != 3 or not fix:
        return 0
    shape, head, rc = parts
    with _locked():
        try:
            entries = _fresh(_load(strict=True), cfg)
        except Refused as e:
            say("spark history: " + e.hint)
            return 1
        rec = next((e for e in entries if _kind(e) == KIND_FAIL and e.get("shape") == shape), None)
        if rec is None:
            rec = {"kind": KIND_FAIL, "name": head, "note": fix, "shape": shape,
                   "head": head, "rc": rc, "count": 0}
            entries.append(rec)
        rec.update({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "note": fix,
                    "count": int(rec.get("count", 0)) + 1})
        mine = [e for e in entries if _kind(e) == KIND_FAIL]
        if len(mine) > PER_NAME:
            drop = mine[:len(mine) - PER_NAME]
            entries = [e for e in entries if e not in drop]
        _save(entries)
        write_fails_index(entries, cfg)
    try:
        os.remove(FAIL_PENDING)
    except OSError:
        pass
    return 0


def write_fails_index(entries=None, cfg=None):
    """state/fails, the ONE file the widgets' prompt hook may read: one
    `hash head rc fix` line per living fail record. Retirement applies
    here too, so the hook never offers a fix whose tool is gone."""
    if entries is None:
        entries = _fresh(_load(), cfg)
    lines = []
    for e in entries:
        if _kind(e) != KIND_FAIL or _retired(e, "path", None):
            continue
        lines.append("%s %s %s %s\n" % (e.get("shape", ""), e.get("head", ""), e.get("rc", ""),
                                         SECRET_RE.sub(r"\1=...", e["note"])))
    try:
        from . import state_dir
        state_dir()
        fd = os.open(FAILS_INDEX, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("".join(lines))
    except OSError:
        log_exc("fails index")


def _paragraph(head, mine):
    """`head` and the notes, newest first, at most SEND_MAX chars."""
    lines, total = [], 0
    for e in reversed(mine):
        line = "- " + e["note"]
        if total + len(line) > SEND_MAX:
            break
        lines.append(line)
        total += len(line)
    return head + "\n".join(lines) + "\n" if lines else ""


def block(cfg, name, data):
    """Contract 10: the paragraph a ? about `name` carries, or "".
    Retirement by quote is this kind's rule and no other's."""
    name = _name(name)
    if not name:
        return ""
    with _locked():
        all_e = _load()
        if not all_e:
            return ""
        mine, alive = _mine(cfg, KIND_EDIT, name, data)
        if len(alive) != len(all_e):
            try:
                _save(alive)
            except OSError:
                pass
    return _paragraph("Declined before -- do not raise these again:\n", mine)


def answered(cfg, name):
    """Contract 12: (the paragraph a question round carries, the folded
    questions already answered). Nothing invalidates these but age and
    `ledger clear`: the plan may move, an answer stays an answer. The
    comparison key is ask.bare on BOTH sides, so a record written before
    v1.30 (with its `1.` or its anchor mark still on) matches too."""
    from . import ask as askmod
    name = _name(name)
    if not name:
        return "", set()
    mine, _alive = _mine(cfg, KIND_ASK, name)
    folded = set(askmod.bare(e["note"]) for e in mine)
    return _paragraph("Answered before -- do not ask these again:\n", mine), folded


def _day(offset=0):
    """A YYYY-MM-DD date `offset` days from today, local time."""
    return time.strftime("%Y-%m-%d", time.localtime(time.time() + offset * 86400))


def drill_due(name):
    """Contract 13: the scheduled items for `name` due today or earlier,
    soonest first. A rested item (no `due`) does not come back; a drill
    record never ages out (RULES: drill age is False)."""
    name = _name(name)
    today = _day()
    mine = [e for e in _load() if _kind(e) == KIND_DRILL and e["name"] == name
            and e.get("due") and e["due"] <= today]
    mine.sort(key=lambda e: e.get("due", ""))
    return mine


def drill_grade(name, question, answer, right, cfg=None):
    """Contract 13: record how a drill item went and when it is next due --
    the schedule, not a suppression. The item is keyed by its question; the
    answer span rides so a later session can re-ask it. `drill.schedule`
    owns the policy (right twice rests it, a miss widens the interval); this
    only persists the state it returns. Drill records never age out."""
    from . import drill as drillmod
    from . import text as textmod
    name = _name(name)
    if not name:
        raise Refused("a drill schedule needs --name NAME (the source's name)")
    q = " ".join((question or "").split())[:NOTE_MAX]
    a = " ".join((answer or "").split())[:NOTE_MAX]
    key = textmod.fold(q)
    with _locked():
        entries = _load(strict=True)
        rec = next((e for e in entries if _kind(e) == KIND_DRILL and e["name"] == name
                    and textmod.fold(e.get("note", "")) == key), None)
        if rec is None:
            rec = {"kind": KIND_DRILL, "name": name, "note": q, "answer": a, "misses": 0, "streak": 0, "due": ""}
            entries.append(rec)
        misses, streak, off = drillmod.schedule(rec.get("misses", 0), rec.get("streak", 0), right)
        rec.update({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "answer": a,
                    "misses": misses, "streak": streak, "due": "" if off is None else _day(off)})
        mine = [e for e in entries if _kind(e) == KIND_DRILL and e["name"] == name]
        if len(mine) > PER_NAME:
            drop = mine[:len(mine) - PER_NAME]
            entries = [e for e in entries if e not in drop]
        _save(entries)


def drill_listing(name=None):
    """Contract 13's records for a pane: the schedule, soonest due first."""
    name = _name(name) if name else None
    es = [e for e in _load() if _kind(e) == KIND_DRILL and (not name or e["name"] == name)]
    head = (name + ": ") if name else ""
    if not es:
        return [head + "no drill scheduled (spark drill --name NAME keeps a schedule)"]
    out = [head + "%d item%s, soonest due first" % (len(es), "" if len(es) == 1 else "s")]
    for e in sorted(es, key=lambda e: e.get("due") or "~"):
        due = e.get("due") or "rested"
        out.append("  %-10s streak %d, misses %d   %s" % (due, e.get("streak", 0), e.get("misses", 0),
                                                          e["note"][:48] + ("..." if len(e["note"]) > 48 else "")))
    return out


def clear(name=None, kind=KIND_EDIT):
    """Drop this kind's notes, or one name's; the count dropped."""
    name = _name(name) if name else None
    with _locked():
        all_e = _load(strict=True)
        alive = [e for e in all_e if _kind(e) != kind or (name and e["name"] != name)]
        if len(alive) != len(all_e):
            _save(alive)
    return len(all_e) - len(alive)


def _age(ts):
    try:
        secs = time.time() - time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M:%S"))
    except (ValueError, OverflowError):
        return "?"
    days = int(secs // 86400)
    return "today" if days < 1 else ("%dd" % days)


def listing(name=None, kind=KIND_EDIT, empty="no declined note (the pane: d on a note)", noun="note"):
    """One kind's records as lines for a pane: one name's, or every
    name's; newest first. Each kind names its own records."""
    es = _fresh(entries(name, kind), config.load())
    head = (name + ": ") if name else ""
    if not es:
        return [head + empty]
    out = [head + "%d %s%s, newest first" % (len(es), noun, "" if len(es) == 1 else "s")]
    width = max(len(e["name"]) for e in es)
    for e in reversed(es):
        out.append("  %-5s %-*s %s" % (_age(e["ts"]), width, e["name"], e["note"][:60] + ("..." if len(e["note"]) > 60 else "")))
    return out
