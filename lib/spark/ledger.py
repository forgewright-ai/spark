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

import json
import os
import time

from . import MARK, config, log_exc, say, vault

NOTE_MAX = 300        # characters kept of one note
PER_NAME = 30         # notes per name and kind; the oldest goes
TOTAL_MAX = 200       # notes in all
SEND_MAX = 1200       # characters a request carries, newest first

KIND_EDIT, KIND_ASK, KIND_READ, KIND_DRILL = "edit", "ask", "read", "drill"
# The table above, as the code reads it. `age`: SPARK_HISTORY days apply.
# `retire`: what drops a record before its time -- "quote" is contract
# 10's (the note's first quoted span left the text), "never" is every
# other contract's, each for its own stated reason.
RULES = {
    KIND_EDIT: {"age": True, "retire": "quote"},
    KIND_ASK: {"age": True, "retire": "never"},
    KIND_READ: {"age": True, "retire": "never"},
    KIND_DRILL: {"age": False, "retire": "never"},
}


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


def _load(st=None):
    st = st or _store()
    if not st or not os.path.isfile(st[0]):
        return []
    try:
        recs = vault.read_sealed(st[0], st[1])
    except (OSError, vault.SealError):
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
        raise OSError("no account to hold the ledger")
    path, dk, name = st
    users.make_dirs(name)
    vault.write_sealed(path, dk, "ledger", name,
                       "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries).encode("utf-8"))


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
    name = os.path.basename((name or "").strip())
    text = " ".join((note or "").split())
    if not name:
        raise Refused(missing or "a declined note needs --name NAME (the file's name)")
    if not text:
        raise Refused("nothing to keep -- the note comes on stdin")
    text = text[:NOTE_MAX]
    entries = _fresh(_load(), cfg)
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
    name = os.path.basename(name) if name else None
    return [e for e in _load() if _kind(e) == kind and (not name or e["name"] == name)]


def _mine(cfg, kind, name, data=None):
    """(the kind's records for `name`, newest last; every record kept) --
    with this kind's own invalidation applied. `retire: "quote"` needs
    `data`, the text as it is now: a note whose first quoted span has
    left it is dropped from the file here and not sent."""
    from . import text as textmod
    retire = RULES.get(kind, RULES[KIND_EDIT])["retire"]
    alive, mine = [], []
    for e in _fresh(_load(), cfg):
        if _kind(e) == kind and e["name"] == name:
            if retire == "quote" and data is not None:
                qs = textmod.quotes(e["note"])
                if qs and not textmod.anchor(qs[0][0], data):
                    continue                 # retired: the passage changed
            mine.append(e)
        alive.append(e)
    return mine, alive


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
    name = os.path.basename((name or "").strip())
    if not name:
        return ""
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
    `ledger clear`: the plan may move, an answer stays an answer."""
    from . import text as textmod
    name = os.path.basename((name or "").strip())
    if not name:
        return "", set()
    mine, _alive = _mine(cfg, KIND_ASK, name)
    folded = set(textmod.fold(e["note"]) for e in mine)
    return _paragraph("Answered before -- do not ask these again:\n", mine), folded


def _day(offset=0):
    """A YYYY-MM-DD date `offset` days from today, local time."""
    return time.strftime("%Y-%m-%d", time.localtime(time.time() + offset * 86400))


def drill_due(name):
    """Contract 13: the scheduled items for `name` due today or earlier,
    soonest first. A rested item (no `due`) does not come back; a drill
    record never ages out (RULES: drill age is False)."""
    name = os.path.basename((name or "").strip())
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
    name = os.path.basename((name or "").strip())
    if not name:
        raise Refused("a drill schedule needs --name NAME (the source's name)")
    q = " ".join((question or "").split())[:NOTE_MAX]
    a = " ".join((answer or "").split())[:NOTE_MAX]
    key = textmod.fold(q)
    entries = _load()
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
    name = os.path.basename(name) if name else None
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
    name = os.path.basename(name) if name else None
    all_e = _load()
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
