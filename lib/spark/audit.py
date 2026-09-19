# spark.audit -- the sealed audit trail: one JSON record per admin action,
# appended into the box account's store (users/<name>/audit, kind audit),
# numbers and names only -- a command's sha256 prefix and its rc, a verb
# and its rc, a user's name and what was done to it -- never a command's
# text. The FORGE's admin routes write it (do/run, /api/run, a user's
# token rotation), and so do the verbs that mint, remove and rotate
# (spark user add|remove|token --new, spark forge token --new). `spark
# forge audit [N] [--porcelain]` reads it, newest N. Append-only:
# vault.append_sealed holds an existing file to its header first, so a
# file that is not the trail takes no record and is never written over;
# a trail that does not open is one signed line, exit 2 -- the ledger's
# rule. An action is never blocked by its record: a trail that cannot
# take one is a line in forge.log or on the terminal, and the action
# stands.

import json
import os
import time

from . import MARK, log_exc, page, say, vault

FILE = "audit"
KIND = "audit"
DEFAULT_N = 50
NO_OPEN = "the audit trail does not open -- spark user login again"
NO_STORE = "no login here to hold the audit trail -- spark user login NAME"


class Refused(Exception):
    def __init__(self, hint):
        super().__init__(hint)
        self.hint = hint


def _store():
    """(path, dk, name) of the box account's store, or None. The login's
    own, never minted here: a record must not make an account."""
    from . import forge
    st = forge.local_store()
    if isinstance(st, forge._NullStore):
        return None
    return os.path.join(os.path.dirname(st.tdir), FILE), st.dk, st.name


def record(action, ip="cli", **fields):
    """One record onto the trail: {ts, ip, action, ...fields}. Returns ""
    when kept, else the one-line reason for the caller to say or log."""
    rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "ip": ip, "action": action}
    rec.update(fields)
    try:
        st = _store()
        if st is None:
            return NO_STORE
        path, dk, name = st
        from . import users
        users.make_dirs(name)
        vault.append_sealed(path, dk, KIND, name, json.dumps(rec, sort_keys=True).encode("utf-8"))
        return ""
    except (OSError, vault.SealError):
        log_exc("audit")
        return NO_OPEN


def records(n=DEFAULT_N):
    """The newest n records, oldest first; [] before the first. Refused
    with the one line when there is no store or it does not open."""
    st = _store()
    if st is None:
        raise Refused(NO_STORE)
    path, dk, name = st
    if not os.path.isfile(path):
        return []
    try:
        recs = vault.read_sealed(path, dk, KIND, name)
    except (OSError, vault.SealError):
        raise Refused(NO_OPEN)
    out = []
    for raw in recs[-n:] if n > 0 else recs:
        try:
            d = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


def line(rec, porcelain=False):
    """One record as a line: ts, ip, action, then the rest as k=v."""
    rest = " ".join("%s=%s" % (k, rec[k]) for k in sorted(rec) if k not in ("ts", "ip", "action"))
    cols = (str(rec.get("ts", "")), str(rec.get("ip", "")), str(rec.get("action", "")), rest)
    return "\t".join(cols) if porcelain else ("%-19s  %-15s  %-12s  %s" % cols).rstrip()


def cmd_audit(args):
    """spark forge audit [N] [--porcelain]: the newest N admin actions."""
    porcelain = "--porcelain" in args
    words = [a for a in args if a != "--porcelain"]
    if len(words) > 1 or (words and not words[0].isdigit()):
        say("%s forge -- audit takes a count: spark forge audit [N] [--porcelain]" % MARK)
        return 2
    try:
        recs = records(int(words[0]) if words else DEFAULT_N)
    except Refused as e:
        say("%s forge -- %s" % (MARK, e.hint))
        return 2
    if porcelain:
        for r in recs:
            say(line(r, True))
        return 0
    if not recs:
        say("audit    none yet")
        return 0
    page("\n".join(line(r) for r in recs))
    return 0
