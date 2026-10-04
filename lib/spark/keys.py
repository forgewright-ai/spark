# spark.keys -- `spark keys`: the keys the widgets add to your shell.
# The list (each key, what it does, what it replaced there), a key moved
# or left to the shell (`~/.config/spark/keys.env`, read by both widgets
# as a shell starts), and the whole set off or on (SITE_KEYS in site.env:
# off, bootstrap's rc rows add no line and the rc file is left alone).
# What a key replaced is the widget's own record (state/replaced.<shell>,
# written when it changes), else the shell's stock binding from DEFAULTS.

import os
import re

from . import CONFIG_DIR, HOME, MARK, STATE_DIR, config, say

KEYS_ENV = os.path.join(CONFIG_DIR, "keys.env")
SIGN = "%s keys -- the keys spark adds to your shell" % MARK
USAGE = SIGN + """

  spark keys              each key, what it does and what it replaced
  spark keys NAME KEY     move a key: spark keys ask Esc a (Alt-a, Ctrl-g)
  spark keys NAME none    leave that key to your shell
  spark keys reset        the keys as spark ships them
  spark keys off          add no key: spark's line leaves your rc file
  spark keys on           add them again

  the names: ask recall height listen stop
  Enter, Ctrl-U, Ctrl-L and paste keep what they did, and do not move
  SPARK_OFF=1 in the environment starts one shell without the keys
"""

# The keys that move: (name, the key spark ships, what it does). The two
# widgets carry the same names (KEYS_<NAME> in keys.env) and defaults.
NAMES = (("ask", "Esc s", "ask about the line you are on"),
         ("recall", "Esc r", "find a past command by what it did"),
         ("height", "Esc k", "move the row spark writes in"),
         ("listen", "Esc v", "listen, with the voice on"),
         ("stop", "Esc x", "stop the speaking, with the voice on"))
# The keys spark wraps: each keeps the function it had, so none moves.
WRAPPED = (("Enter", "a ? line asks spark; any other runs as before"),
           ("Ctrl-U", "empties the line as before, and spark's row"),
           ("Ctrl-L", "clears the screen as before (zsh)"),
           ("paste", "lands as before; 2 lines or more are named"))
# Ctrl- letters a key may take. The rest belong to the terminal (c d q s
# z), are another key's code (h i j m), are wrapped (l u), or open the
# shell's own key sequences (x: the bash widget's macros ride on it).
CTRL_OK = "abefgknoprtvwy"
ESC_WAIT = "a lone Esc waits up to 1 s for the next key"

# What each shell binds there before spark, in its emacs keymap: the
# answer when the widget has recorded nothing yet. Esc 0-9 is the digit
# argument in both.
DEFAULTS = {
    "zsh": {"Esc a": "accept-and-hold", "Esc b": "backward-word", "Esc c": "capitalize-word",
            "Esc d": "kill-word", "Esc f": "forward-word", "Esc g": "get-line", "Esc h": "run-help",
            "Esc l": "down-case-word", "Esc n": "history-search-forward",
            "Esc p": "history-search-backward", "Esc q": "push-line", "Esc s": "spell-word",
            "Esc t": "transpose-words", "Esc u": "up-case-word", "Esc w": "copy-region-as-kill",
            "Esc x": "execute-named-cmd", "Esc y": "yank-pop", "Esc z": "execute-last-named-cmd",
            "Ctrl-a": "beginning-of-line", "Ctrl-b": "backward-char", "Ctrl-e": "end-of-line",
            "Ctrl-f": "forward-char", "Ctrl-g": "send-break", "Ctrl-k": "kill-line",
            "Ctrl-n": "down-line-or-history", "Ctrl-o": "accept-line-and-down-history",
            "Ctrl-p": "up-line-or-history", "Ctrl-r": "history-incremental-search-backward",
            "Ctrl-t": "transpose-chars", "Ctrl-v": "quoted-insert", "Ctrl-w": "backward-kill-word",
            "Ctrl-y": "yank"},
    "bash": {"Esc b": "backward-word", "Esc c": "capitalize-word", "Esc d": "kill-word",
             "Esc f": "forward-word", "Esc l": "downcase-word",
             "Esc n": "non-incremental-forward-search-history",
             "Esc p": "non-incremental-reverse-search-history", "Esc r": "revert-line",
             "Esc t": "transpose-words", "Esc u": "upcase-word", "Esc y": "yank-pop",
             "Ctrl-a": "beginning-of-line", "Ctrl-b": "backward-char", "Ctrl-e": "end-of-line",
             "Ctrl-f": "forward-char", "Ctrl-g": "abort", "Ctrl-k": "kill-line",
             "Ctrl-n": "next-history", "Ctrl-o": "operate-and-get-next", "Ctrl-p": "previous-history",
             "Ctrl-r": "reverse-search-history", "Ctrl-t": "transpose-chars",
             "Ctrl-v": "quoted-insert", "Ctrl-w": "unix-word-rubout", "Ctrl-y": "yank"},
}
for _sh in DEFAULTS.values():
    _sh.update(("Esc %d" % _n, "digit-argument") for _n in range(10))

_WRAPPED_WORDS = {"enter": "Enter", "return": "Enter", "ctrl-m": "Enter", "ctrl-j": "Enter",
                  "ctrl-u": "Ctrl-U", "ctrl-l": "Ctrl-L", "paste": "paste"}
SPELL = "a key is Esc a, Alt-a or Ctrl-g"


def spell(words):
    """(key, None) for a key spark can spell -- `Esc a` (Alt-a is the same
    key), `Ctrl-g` or `none` -- else (None, why): one line."""
    raw = " ".join(words).strip()
    if raw.lower() == "none":
        return "none", None
    if raw.lower() in _WRAPPED_WORDS:
        return None, "%s is wrapped: it keeps what it did, and no key moves there" % _WRAPPED_WORDS[raw.lower()]
    m = re.fullmatch(r"(?:[Ee]sc[ -]|[Aa]lt-)([a-z0-9])", raw)
    if m:
        return "Esc " + m.group(1), None
    m = re.fullmatch(r"(?:[Cc]trl-|\^)([A-Za-z])", raw)
    if m:
        c = m.group(1).lower()
        if c in CTRL_OK:
            return "Ctrl-" + c, None
        return None, "Ctrl-%s is not free; %s" % (c, SPELL)
    return None, "no key named %s; %s" % (raw, SPELL)


def _valid(val):
    return val == "none" or bool(re.fullmatch(r"Esc [a-z0-9]|Ctrl-[%s]" % CTRL_OK, val))


def current():
    """{name: key}: keys.env over the defaults; a value the widgets would
    not take reads as the default, as it does there."""
    env = config.parse_env(KEYS_ENV)
    out = {}
    for name, default, _ in NAMES:
        val = env.get("KEYS_" + name.upper(), default)
        if re.fullmatch(r"Alt-[a-z0-9]", val):
            val = "Esc " + val[-1]
        out[name] = val if _valid(val) else default
    return out


def recorded(shell):
    """{name: (key, was)} from the widget's own record: what it found on
    each key before it bound it, `-` for nothing."""
    out = {}
    try:
        with open(os.path.join(STATE_DIR, "replaced." + shell), encoding="utf-8", errors="replace") as f:
            for line in f.read().splitlines()[:16]:
                part = line.split("\t")
                if len(part) == 3 and part[2].isprintable():
                    out[part[0]] = (part[1], part[2][:40])
    except OSError:
        pass
    return out


def was(shell, name, key, record=None):
    """What `key` did in this shell before spark took it: '' for nothing."""
    record = recorded(shell) if record is None else record
    if name in record and record[name][0] == key:
        return "" if record[name][1] == "-" else record[name][1]
    return DEFAULTS.get(shell, {}).get(key, "")


def rows(shell):
    """[(name, key, does, was)] for the keys that move."""
    cur, record = current(), recorded(shell)
    return [(name, cur[name], does, "" if cur[name] == "none" else was(shell, name, cur[name], record))
            for name, _, does in NAMES]


def wrapped(shell):
    return [(key, does) for key, does in WRAPPED if not (key == "Ctrl-L" and shell != "zsh")]


def _tilde(path):
    return "~" + path[len(HOME):] if path.startswith(HOME + os.sep) else path


def _show(cfg):
    from . import site
    shell = site.login_shell()
    known = site.rc_file(shell) is not None
    if not cfg.keys:
        head = "off: spark adds no key to your shell -- spark keys on adds them"
    elif not known:
        head = "%s has no prompt line (bash 4+ or zsh do)" % shell
    else:
        head = "on, in %s" % shell
    say("%s keys -- %s" % (MARK, head))
    for name, key, does, old in rows(shell):
        say(("%-7s %-7s %-36s %s" % (name, key, does, "was " + old if old else "")).rstrip())
    for key, does in wrapped(shell):
        say("%-7s %-7s %s" % ("", key, does))
    say(ESC_WAIT)
    return 0


def _write(kv):
    from . import site
    site.set_keys(_file=KEYS_ENV, _quiet=True, **kv)


def _move(name, words):
    from . import site
    names = [n for n, _, _ in NAMES]
    if name.lower() in _WRAPPED_WORDS:
        say("%s keys -- %s is wrapped: it keeps what it did, and it does not move" % (MARK, _WRAPPED_WORDS[name.lower()]))
        return 2
    if name not in names:
        say("%s keys -- no word %s; spark keys -h lists them" % (MARK, name))
        return 2
    if not words:
        say("%s keys -- %s needs a key: spark keys %s Esc a" % (MARK, name, name))
        return 2
    key, why = spell(words)
    if why:
        say("%s keys -- %s" % (MARK, why))
        return 2
    cur = current()
    if key != "none":
        for other in names:
            if other != name and cur[other] == key:
                say("%s keys -- %s is %s's key; move %s first, or pick another" % (MARK, key, other, other))
                return 2
    if cur[name] == key:
        say("* nothing changed")
        return 0
    _write({"KEYS_" + name.upper(): key})
    if key == "none":
        say("* %s has no key now -- the next shell leaves it alone" % name)
        return 0
    shell = site.login_shell()
    old = DEFAULTS.get(shell, {}).get(key, "")
    say("* %s is %s now%s -- the next shell has it"
        % (name, key, ", in place of %s's %s" % (shell, old) if old else ""))
    return 0


def _reset():
    cur = current()
    try:
        os.remove(KEYS_ENV)
    except OSError:
        pass
    if all(cur[name] == default for name, default, _ in NAMES):
        say("* nothing changed")
        return 0
    say("* the keys are spark's own again -- the next shell has them")
    return 0


def _off(cfg):
    from . import site, uninstall
    gone = []
    for name in uninstall.RC_CANDIDATES:
        path = os.path.join(HOME, name)
        try:
            if uninstall.strip_rc_line(path):
                gone.append(_tilde(path))
        except OSError as e:
            say("! %s: %s" % (_tilde(path), e.strerror or e))
            return 1
    if not cfg.keys and not gone:
        say("* nothing changed")
        return 0
    site.set_keys(_quiet=True, SITE_KEYS="off")
    if gone:
        say("* spark's line is out of %s -- open a new shell" % " and ".join(gone))
    else:
        say("* spark adds no key to your shell now")
    if not os.environ.get("SPARK_NO_APPLY"):
        from . import check
        check.refresh()
    return 0


def _on(cfg):
    from . import site
    state, _ = site.rc_hook_state(site.login_shell())
    if cfg.keys and state == "hook":
        say("* nothing changed")
        return 0
    site.set_keys(_quiet=True, SITE_KEYS="on")
    rc = site.apply(["rc", "rc-login"])
    if rc == 0:
        say("* open a new shell (exec $SHELL): it has the keys")
    return rc


def main(args):
    if args and args[0] in ("-h", "--help", "help"):
        say(USAGE.rstrip())
        return 0
    cfg = config.load()
    if not args or args == ["status"]:
        return _show(cfg)
    if len(args) == 1 and args[0] in ("off", "on", "reset"):
        return {"off": _off, "on": _on}[args[0]](cfg) if args[0] != "reset" else _reset()
    return _move(args[0], args[1:])
