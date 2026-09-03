# spark.soul -- who spark is on this machine: a paragraph the user owns in
# ~/.config/spark/soul (0600). Absent, the built-in DEFAULT applies; for
# this version SPARK_PERSONA_EXTRA is read as a fallback between the two.
#
#   spark soul            show it, and where it comes from
#   spark soul edit       write it in your editor
#   spark soul reset      back to the built-in paragraph

import os
import shutil
import subprocess

from . import CONFIG_DIR, MARK, SOUL_FILE, config, say

SOUL_MAX = 4000

DEFAULT = (
    "You are spark, the AI on this machine. You run here, on hardware the "
    "user owns; nothing you are told leaves it. You are here to answer, to "
    "explain, to write, and to hand the user a command when one is what "
    "they need. Speak plainly, in the user's language. Say when you do not "
    "know. Never invent a flag, a path, or a command."
)

SOUL_USAGE = """%s soul -- who it is

  spark ships with a default soul; spark soul edit writes your own.

  spark soul                    the paragraph in use, and where it comes from
  spark soul edit               write your own in $VISUAL / $EDITOR (0600)
  spark soul reset              back to the default

  The file is ~/.config/spark/soul, plain text, at most %d characters.
""" % (MARK, SOUL_MAX)


def read(cfg):
    """(text, source) -- source is file, env or builtin. The file wins, then
    SPARK_PERSONA_EXTRA (deprecated), then DEFAULT. Stripped, capped."""
    try:
        with open(SOUL_FILE, encoding="utf-8", errors="replace") as f:
            t = f.read().strip()
        if t:
            return t[:SOUL_MAX], "file"
    except OSError:
        pass
    extra = cfg.persona_extra.strip() if cfg is not None else ""
    if extra:
        return extra[:SOUL_MAX], "env"
    return DEFAULT, "builtin"


def text(cfg):
    return read(cfg)[0]


def write(cfg, t):
    """Write the soul file, 0600, no terminal needed (the page calls this
    too). cfg is unused for now; kept so callers read like read()."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    fd = os.open(SOUL_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write((t or "").strip()[:SOUL_MAX] + "\n")
    os.chmod(SOUL_FILE, 0o600)


def _editor():
    for var in ("VISUAL", "EDITOR"):
        v = os.environ.get(var)
        if v:
            return v.split()
    for name in ("micro", "nano", "vi"):
        if shutil.which(name):
            return [name]
    return []


def _show(cfg):
    t, source = read(cfg)
    say("%s  %s  %s  %d chars" % ("soul", source, SOUL_FILE, len(t)))
    say(t)
    return 0


def _edit(cfg):
    ed = _editor()
    if not ed:
        say("spark soul: no editor found -- set $EDITOR, or write %s by hand" % SOUL_FILE)
        return 1
    if not os.path.isfile(SOUL_FILE):
        t, source = read(cfg)
        write(cfg, t)
        say("ok     seeded       from the %s paragraph" % ("SPARK_PERSONA_EXTRA" if source == "env" else "built-in"))
    else:
        os.chmod(SOUL_FILE, 0o600)
    try:
        rc = subprocess.call(ed + [SOUL_FILE])
    except OSError as e:
        say("spark soul: cannot run %s: %s" % (ed[0], e))
        return 1
    if rc != 0:
        say("spark soul: %s exited %d -- the file is as it left it" % (ed[0], rc))
    try:
        with open(SOUL_FILE, encoding="utf-8", errors="replace") as f:
            raw = f.read().strip()
    except OSError:
        raw = ""
    n = len(raw)
    if n > SOUL_MAX:
        say("ok     soul         %d chars, over the cap, cut at %d" % (n, SOUL_MAX))
    elif n == 0:
        say("ok     soul         empty -- the built-in paragraph applies")
    else:
        say("ok     soul         %d chars, yours" % n)
    from . import check
    check.refresh()
    return 0


def _reset():
    try:
        os.remove(SOUL_FILE)
        say("ok     soul         built-in again")
    except FileNotFoundError:
        say("ok     soul         built-in already")
    except OSError as e:
        say("spark soul: cannot remove %s: %s" % (SOUL_FILE, e))
        return 1
    from . import check
    check.refresh()
    return 0


def cmd_soul(args):
    cfg = config.load()
    if not args or args[0] == "show":
        return _show(cfg)
    if args[0] in ("-h", "--help", "help"):
        say(SOUL_USAGE.rstrip())
        return 0
    if args[0] == "edit":
        return _edit(cfg)
    if args[0] == "reset":
        return _reset()
    say(SOUL_USAGE.rstrip())
    return 2
