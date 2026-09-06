# spark.ledger -- the notes you declined in the editor, kept per file
# name, sealed in the account's store (users/<name>/ledger), written only
# by you (the pane's `d` key runs `spark edit --decline --name NAME` with
# the note on stdin). The next `?` about a file of that name carries them
# -- "Declined before -- do not raise these again" -- so a note you have
# already weighed does not come back. A declined note retires: it leaves
# the request (and the file) once the span it quoted has left the text,
# and after SPARK_HISTORY days like a thread.
#
#   spark ledger [NAME]        the notes, newest first (one file's, or all)
#   spark ledger clear [NAME]  drop them (one file's, or all)

import json
import os
import time

from . import MARK, config, log_exc, say, vault

NOTE_MAX = 300        # characters kept of one note
PER_NAME = 30         # notes per file name; the oldest goes
TOTAL_MAX = 200       # notes in all
SEND_MAX = 1200       # characters a ? carries, newest first



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
    """Without the notes older than SPARK_HISTORY days."""
    days = cfg.history if cfg is not None else 30
    if days <= 0:
        return entries
    cutoff = time.time() - days * 86400
    out = []
    for e in entries:
        try:
            ts = time.mktime(time.strptime(e.get("ts", ""), "%Y-%m-%d %H:%M:%S"))
        except (ValueError, OverflowError):
            ts = 0
        if ts >= cutoff:
            out.append(e)
    return out


def decline(name, note, cfg=None):
    """Keep one declined note under a file name; returns it as kept."""
    name = os.path.basename((name or "").strip())
    text = " ".join((note or "").split())
    if not name:
        raise Refused("a declined note needs --name NAME (the file's name)")
    if not text:
        raise Refused("nothing to decline -- the note comes on stdin")
    text = text[:NOTE_MAX]
    entries = _fresh(_load(), cfg)
    entries = [e for e in entries if not (e["name"] == name and e["note"] == text)]
    entries.append({"name": name, "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "note": text})
    mine = [e for e in entries if e["name"] == name]
    if len(mine) > PER_NAME:
        drop = mine[:len(mine) - PER_NAME]
        entries = [e for e in entries if e not in drop]
    if len(entries) > TOTAL_MAX:
        entries = entries[len(entries) - TOTAL_MAX:]
    _save(entries)
    return text


def entries(name=None):
    """The kept notes, oldest first; one file's when a name is given."""
    name = os.path.basename(name) if name else None
    return [e for e in _load() if not name or e["name"] == name]


def block(cfg, name, data):
    """The paragraph a ? about `name` carries, or "": the file's declined
    notes, newest first, at most SEND_MAX chars. A note whose first
    quoted span is no longer in `data` has retired: it is dropped from
    the file here and not sent."""
    from . import text as textmod
    name = os.path.basename((name or "").strip())
    if not name:
        return ""
    all_e = _load()
    if not all_e:
        return ""
    fresh = _fresh(all_e, cfg)
    keep, mine = [], []
    for e in fresh:
        if e["name"] == name:
            qs = textmod.quotes(e["note"])
            if qs and not textmod.anchor(qs[0][0], data):
                continue                     # retired: the passage changed
            mine.append(e)
        keep.append(e)
    if len(keep) != len(all_e):
        try:
            _save(keep)
        except OSError:
            pass
    if not mine:
        return ""
    lines, total = [], 0
    for e in reversed(mine):
        line = "- " + e["note"]
        if total + len(line) > SEND_MAX:
            break
        lines.append(line)
        total += len(line)
    return "Declined before -- do not raise these again:\n" + "\n".join(lines) + "\n"


def clear(name=None):
    """Drop every note, or one file's; the count dropped."""
    name = os.path.basename(name) if name else None
    all_e = _load()
    keep = [e for e in all_e if name and e["name"] != name]
    if len(keep) != len(all_e):
        _save(keep)
    return len(all_e) - len(keep)


def _age(ts):
    try:
        secs = time.time() - time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M:%S"))
    except (ValueError, OverflowError):
        return "?"
    days = int(secs // 86400)
    return "today" if days < 1 else ("%dd" % days)


def listing(name=None):
    """The declined notes as lines for the editor's pane: one file's, or
    every file's; newest first."""
    es = _fresh(entries(name), config.load())
    head = (name + ": ") if name else ""
    if not es:
        return [head + "no declined note (the pane: d on a note)"]
    out = [head + "%d note%s, newest first" % (len(es), "" if len(es) == 1 else "s")]
    width = max(len(e["name"]) for e in es)
    for e in reversed(es):
        out.append("  %-5s %-*s %s" % (_age(e["ts"]), width, e["name"], e["note"][:60] + ("..." if len(e["note"]) > 60 else "")))
    return out


def cmd_ledger(args):
    # moved into the editor in v1.7: one line naming where it lives, no forwarding
    say("%s ledger -- gone: in micro, at the spark> prompt: ledger, ledger clear" % MARK)
    return 2
