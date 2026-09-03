# spark.memory -- the facts spark recalls on every answer: one per line in
# ~/.config/spark/memory (0600), written only by the user. Config, not
# state: it survives `spark history clear` and the pruning of turns.
#
#   spark remember <words>     keep a fact
#   spark forget N | <words>   drop one, by number or by substring
#   spark memory               list them; on | off | clear

import os

from . import CONFIG_DIR, MARK, MEMORY_FILE, SPARK_ENV, config, say

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


def _lines():
    """Every line of the file, as written (comments and blanks included)."""
    try:
        with open(MEMORY_FILE, encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()
    except OSError:
        return []


def _all_facts():
    """The facts in the file, uncapped, ignoring the on/off switch."""
    return [ln.strip() for ln in _lines() if ln.strip() and not ln.lstrip().startswith("#")]


def facts(cfg):
    """The facts that go into a request: [] when memory is off; at most
    FACTS_MAX of them and TOTAL_MAX characters, oldest first."""
    if cfg is not None and not cfg.memory:
        return []
    out, total = [], 0
    for fact in _all_facts()[:FACTS_MAX]:
        fact = fact[:FACT_MAX]
        if total + len(fact) > TOTAL_MAX:
            break
        out.append(fact)
        total += len(fact)
    return out


def _write(lines):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    fd = os.open(MEMORY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("".join(ln + "\n" for ln in lines))
    os.chmod(MEMORY_FILE, 0o600)


def block(cfg):
    """The paragraph for the system prompt, or "" when there is nothing."""
    fs = facts(cfg)
    if not fs:
        return ""
    return "About %s, remembered:\n" % cfg.user + "\n".join("- " + f for f in fs)


def _refresh():
    from . import check
    check.refresh()


class Refused(Exception):
    """A fact that cannot be kept or dropped. reason: empty | long |
    comment | duplicate | full ; hint: one line for a human."""

    def __init__(self, reason, hint):
        super().__init__(hint)
        self.reason, self.hint = reason, hint


def remember(text):
    """Keep one fact (whitespace folded); returns it as written. Raises
    Refused. The prompt and the page share this."""
    fact = " ".join((text or "").split())
    if not fact:
        raise Refused("empty", "nothing to keep -- say it in words")
    if len(fact) > FACT_MAX:
        raise Refused("long", "%d chars -- a fact is at most %d" % (len(fact), FACT_MAX))
    if fact.startswith("#"):
        raise Refused("comment", "a fact cannot start with # -- that is a comment")
    have = _all_facts()
    if fact.lower() in (h.lower() for h in have):
        raise Refused("duplicate", "already kept: %s" % fact)
    if len(have) >= FACTS_MAX:
        raise Refused("full", "%d facts already -- spark forget one first" % FACTS_MAX)
    _write(_lines() + [fact])
    _refresh()
    return fact


def forget_n(n):
    """Drop fact N as `spark memory` numbers them; the fact, or None when
    there is no such number."""
    lines = _lines()
    idx = [i for i, ln in enumerate(lines) if ln.strip() and not ln.lstrip().startswith("#")]
    if not 1 <= n <= len(idx):
        return None
    fact = lines[idx[n - 1]].strip()
    del lines[idx[n - 1]]
    _write(lines)
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
        say("%s  %s  %d fact%s  %s" % ("memory", "on" if cfg.memory else "off", len(fs), "" if len(fs) == 1 else "s", MEMORY_FILE))
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
        try:
            os.remove(MEMORY_FILE)
            say("ok     memory       cleared")
        except FileNotFoundError:
            say("ok     memory       nothing was kept")
        except OSError as e:
            say("spark memory: cannot remove %s: %s" % (MEMORY_FILE, e))
            return 1
        _refresh()
        return 0
    say(MEMORY_USAGE.rstrip())
    return 2
