# spark.memory -- the facts spark recalls on every answer: one per line,
# sealed in the account's store (users/<name>/memory), written only by
# the user. Config, not state: it survives `spark history clear` and the
# pruning of turns. The pre-v1.4 plaintext ~/.config/spark/memory is
# read as the fallback until the first write seals and removes it.
#
#   spark remember <words>     keep a fact
#   spark forget N | <words>   drop one, by number or by substring
#   spark memory               list them; on | off | clear

import os

from . import MARK, MEMORY_FILE, SPARK_ENV, config, log_exc, say, vault

FACT_MAX = 200        # characters per fact
FACTS_MAX = 40        # facts kept
TOTAL_MAX = 2000      # characters sent, all facts together

MEMORY_USAGE = """%s memory -- what it keeps

  spark memory                  the facts, numbered
  spark memory on | off         recall them on every answer, or not
  spark memory clear            forget them all
  spark remember <words>        keep a fact (at most %d chars, %d facts)
  spark forget N                drop fact N as listed above
  spark forget <words>          drop the one fact containing the words

  The file is ~/.config/spark/memory, one fact per line, # for comments.
  Quote a fact that carries ( ) * ? or | -- the shell eats them first.
""" % (MARK, FACT_MAX, FACTS_MAX)


def store_of(name, dk):
    """The (sealed path, dk, name) triple of one named user's memory --
    what the FORGE passes for the requesting user."""
    from . import users
    return os.path.join(users.user_dir(name), "memory"), dk, name


def _store():
    """(sealed path, dk, name) of this machine's own account, or None --
    no account, or its key not held here (a client machine)."""
    from . import users
    name, _ = users.account()
    if name and users.exists(name):
        dk = users.account_key()
        if dk:
            return store_of(name, dk)
    return None


def sealed_exists():
    """Whether the account's sealed memory file is on this machine."""
    st = _store()
    return bool(st) and os.path.isfile(st[0])


def _lines(st=None):
    """Every line of the memory, as written (comments and blanks too):
    the sealed store first, the pre-v1.4 plaintext as the fallback.
    `st` names whose (store_of); None is this machine's own account."""
    st = st or _store()
    if st and os.path.isfile(st[0]):
        try:
            recs = vault.read_sealed(st[0], st[1])
            return recs[0].decode("utf-8", "replace").splitlines() if recs else []
        except (OSError, vault.SealError):
            return []
    if st and st != _store():
        return []                  # a named user with no memory yet: never the box's file
    try:
        with open(MEMORY_FILE, encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()
    except OSError:
        return []


def _all_facts(st=None):
    """The facts in the file, uncapped, ignoring the on/off switch."""
    return [ln.strip() for ln in _lines(st) if ln.strip() and not ln.lstrip().startswith("#")]


def facts(cfg, st=None):
    """The facts that go into a request: [] when memory is off; at most
    FACTS_MAX of them and TOTAL_MAX characters, oldest first."""
    if cfg is not None and not cfg.memory:
        return []
    out, total = [], 0
    for fact in _all_facts(st)[:FACTS_MAX]:
        fact = fact[:FACT_MAX]
        if total + len(fact) > TOTAL_MAX:
            break
        out.append(fact)
        total += len(fact)
    return out


def _write(lines, st=None):
    """Seal the memory into the named store (minting this machine's own
    account when none is named and none exists) and claim the plaintext
    away."""
    from . import forge
    own = st is None
    st = st or _store()
    if st is None:
        forge.local_store(provision=True)
        st = _store()
    if st is None:
        log_exc("memory store")
        raise OSError("no account to hold the memory")
    path, dk, name = st
    from . import users
    users.make_dirs(name)
    vault.write_sealed(path, dk, "memory", name, "".join(ln + "\n" for ln in lines).encode("utf-8"))
    if own:
        try:
            os.remove(MEMORY_FILE)
        except OSError:
            pass


def block(cfg, st=None):
    """The paragraph for the system prompt, or "" when there is nothing.
    A named user's block carries their name; the box's carries SITE_USER."""
    fs = facts(cfg, st)
    if not fs:
        return ""
    who = st[2] if st else (cfg.user if cfg else "")
    return "About %s, remembered:\n" % who + "\n".join("- " + f for f in fs)


def _refresh():
    from . import check
    check.refresh()


class Refused(Exception):
    """A fact that cannot be kept or dropped. reason: empty | long |
    comment | duplicate | full ; hint: one line for a human."""

    def __init__(self, reason, hint):
        super().__init__(hint)
        self.reason, self.hint = reason, hint


def remember(text, st=None):
    """Keep one fact (whitespace folded); returns it as written. Raises
    Refused. The prompt and the page share this; `st` names whose memory."""
    fact = " ".join((text or "").split())
    if not fact:
        raise Refused("empty", "nothing to keep -- say it in words")
    if len(fact) > FACT_MAX:
        raise Refused("long", "%d chars -- a fact is at most %d" % (len(fact), FACT_MAX))
    if fact.startswith("#"):
        raise Refused("comment", "a fact cannot start with # -- that is a comment")
    have = _all_facts(st)
    if fact.lower() in (h.lower() for h in have):
        raise Refused("duplicate", "already kept: %s" % fact)
    if len(have) >= FACTS_MAX:
        raise Refused("full", "%d facts already -- spark forget one first" % FACTS_MAX)
    _write(_lines(st) + [fact], st)
    _refresh()
    return fact


def forget_n(n, st=None):
    """Drop fact N as `spark memory` numbers them; the fact, or None when
    there is no such number."""
    lines = _lines(st)
    idx = [i for i, ln in enumerate(lines) if ln.strip() and not ln.lstrip().startswith("#")]
    if not 1 <= n <= len(idx):
        return None
    fact = lines[idx[n - 1]].strip()
    del lines[idx[n - 1]]
    _write(lines, st)
    _refresh()
    return fact


def cmd_remember(words):
    if words and words[0] in ("-h", "--help", "help"):
        say(MEMORY_USAGE.rstrip())
        return 0
    try:
        fact = remember(" ".join(words or []))
    except Refused as e:
        say("spark remember: " + e.hint)
        return 1
    say("ok     remembered   %s" % fact)
    return 0


def cmd_forget(args):
    if not args:
        say(MEMORY_USAGE.rstrip())
        return 2
    if args[0] in ("-h", "--help", "help"):
        say(MEMORY_USAGE.rstrip())
        return 0
    lines = _lines()
    idx = [i for i, ln in enumerate(lines) if ln.strip() and not ln.lstrip().startswith("#")]
    if not idx:
        say("spark forget: nothing is remembered")
        return 1
    if len(args) == 1 and args[0].isdigit():
        fact = forget_n(int(args[0]))
        if fact is None:
            say("spark forget: no fact %s -- spark memory lists 1..%d" % (args[0], len(idx)))
            return 1
        say("ok     forgot       %s" % fact)
        return 0
    needle = " ".join(args).lower()
    hits = [i for i in idx if needle in lines[i].lower()]
    if not hits:
        say("spark forget: no fact contains: %s" % " ".join(args))
        return 1
    if len(hits) > 1:
        say("spark forget: %d facts match -- say which by number:" % len(hits))
        for i in hits:
            say("  %-3d %s" % (idx.index(i) + 1, lines[i].strip()))
        return 1
    fact = forget_n(idx.index(hits[0]) + 1)
    say("ok     forgot       %s" % fact)
    return 0


def cmd_memory(args):
    cfg = config.load()
    if not args:
        fs = _all_facts()
        st = _store()
        where = (st[0] + " (sealed)") if st and os.path.isfile(st[0]) else MEMORY_FILE
        say("%s  %s  %d fact%s  %s" % ("memory", "on" if cfg.memory else "off", len(fs), "" if len(fs) == 1 else "s", where))
        for n, f in enumerate(fs, 1):
            say("  %-3d %s" % (n, f))
        return 0
    if args[0] in ("-h", "--help", "help"):
        say(MEMORY_USAGE.rstrip())
        return 0
    if args[0] in ("on", "off"):
        from . import site
        site.set_keys(_file=SPARK_ENV, SPARK_MEMORY=args[0])
        _refresh()
        return 0
    if args[0] == "clear":
        removed = False
        st = _store()
        try:
            if st and os.path.isfile(st[0]):
                os.remove(st[0])
                removed = True
            if os.path.isfile(MEMORY_FILE):
                os.remove(MEMORY_FILE)
                removed = True
        except OSError as e:
            say("spark memory: cannot clear: %s" % e)
            return 1
        say("ok     memory       cleared" if removed else "ok     memory       nothing was kept")
        _refresh()
        return 0
    say(MEMORY_USAGE.rstrip())
    return 2
