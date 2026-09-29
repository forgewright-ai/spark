# spark.soul -- who spark is on this machine: a paragraph the user owns in
# ~/.config/spark/soul (0600). Absent, the built-in DEFAULT applies; for
# this version SPARK_PERSONA_EXTRA is read as a fallback between the two.
#
# Two parts once `spark awaken` has run: DEFAULT is the fixed core (local,
# plain, never invent a flag, a path or a command), and the personality
# paragraph the birth wrote lives in ~/.config/spark/personality (0600),
# added after the core. A soul file of your own replaces both, whole, as
# it always did ("core replaced").
#
#   spark soul            show it, and where it comes from
#   spark soul edit       write it in your editor (after awaken: the
#                         personality; --core: the whole soul file)
#   spark soul reset      back to the built-in paragraph

import os
import shutil
import subprocess

from . import CONFIG_DIR, MARK, SOUL_FILE, config, say

SOUL_MAX = 4000
PERSONALITY_FILE = os.path.join(CONFIG_DIR, "personality")

DEFAULT = (
    "You are spark, the AI on this machine. You run here, on hardware the "
    "user owns; nothing you are told leaves it. You are here to answer, to "
    "explain, to write, and to hand the user a command when one is what "
    "they need. Speak plainly, in the user's language. Say when you do not "
    "know. Never invent a flag, a path, or a command."
)
# the core and the personality together stay within SOUL_MAX
PERSONALITY_MAX = SOUL_MAX - len(DEFAULT) - 2

SOUL_USAGE = """%s soul -- who it is

  spark ships with a default soul; spark soul edit writes your own.

  spark soul                    the paragraph in use, and where it comes from
  spark soul edit               write your own in $VISUAL / $EDITOR (0600)
  spark soul edit --core        the whole soul, when spark awaken gave it a
                                personality (bare edit changes only that)
  spark soul reset              back to the default

  The file is ~/.config/spark/soul, plain text, at most %d characters.
  spark awaken writes ~/.config/spark/personality, one paragraph added
  after the built-in core. A soul file of your own replaces both.
""" % (MARK, SOUL_MAX)


def personality():
    """The personality paragraph (spark awaken, or spark soul edit after
    it), whitespace folded and capped; '' when there is none."""
    try:
        with open(PERSONALITY_FILE, encoding="utf-8", errors="replace") as f:
            return " ".join(f.read().split())[:PERSONALITY_MAX]
    except OSError:
        return ""


def has_personality():
    """Whether awaken left a personality file: then a bare `spark soul
    edit` edits the paragraph, and the core stays."""
    return os.path.isfile(PERSONALITY_FILE)


def read(cfg):
    """(text, source) -- source is file, env, personality or builtin. The
    file wins, then SPARK_PERSONA_EXTRA (deprecated), then DEFAULT with the
    personality paragraph after it, then DEFAULT. Stripped, capped."""
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
    p = personality()
    if p:
        return DEFAULT + "\n\n" + p, "personality"
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


def write_personality(t):
    """Write the personality paragraph, 0600, atomically (awaken, and a
    bare `spark soul edit` after it)."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = PERSONALITY_FILE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(" ".join((t or "").split())[:PERSONALITY_MAX] + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, PERSONALITY_FILE)


def write_edit(cfg, t):
    """What `spark soul edit` would write, for the page's editor, which
    shows the whole soul and sends it back whole. No personality, or a
    soul file of your own: the soul file, as always. A personality and no
    soul file: the text after the unchanged core is the personality; a
    changed core is a whole replacement, the soul file. Returns the part
    written: file or personality."""
    t = (t or "").strip()
    if has_personality() and not os.path.isfile(SOUL_FILE) and t.startswith(DEFAULT):
        write_personality(t[len(DEFAULT):])
        return "personality"
    write(cfg, t)
    return "file"


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
    if source == "personality":
        p = personality()
        say("%s  %s  %s  %d characters" % ("soul", "built-in core + personality", PERSONALITY_FILE, len(t)))
        say(DEFAULT)
        say("")
        say(p)
        return 0
    say("%s  %s  %s  %d characters" % ("soul", source, SOUL_FILE, len(t)))
    say(t)
    if source == "file" and has_personality():
        say("")
        say("Your soul file replaces the core and the personality (spark soul reset uses them).")
    return 0


def _edit_personality():
    """A bare `spark soul edit` after awaken: the personality paragraph
    alone, in the editor; the core stays."""
    ed = _editor()
    if not ed:
        say("spark soul: no editor found -- set $EDITOR, or write %s by hand" % PERSONALITY_FILE)
        return 1
    os.chmod(PERSONALITY_FILE, 0o600)
    try:
        rc = subprocess.call(ed + [PERSONALITY_FILE])
    except OSError as e:
        say("spark soul: cannot run %s: %s" % (ed[0], e))
        return 1
    if rc != 0:
        say("spark soul: %s exited %d -- the file is as it left it" % (ed[0], rc))
    try:
        with open(PERSONALITY_FILE, encoding="utf-8", errors="replace") as f:
            raw = " ".join(f.read().split())
    except OSError:
        raw = ""
    n = len(raw)
    if n > PERSONALITY_MAX:
        say("ok     personality  %d characters, over the cap, cut at %d" % (n, PERSONALITY_MAX))
    elif n == 0:
        say("ok     personality  empty -- the built-in core alone applies")
    else:
        say("ok     personality  %d characters, after the built-in core" % n)
    say("The core stays. spark soul edit --core replaces the whole soul.")
    from . import check
    check.refresh()
    return 0


def _edit(cfg, core=False):
    if not core and has_personality() and not os.path.isfile(SOUL_FILE):
        return _edit_personality()
    ed = _editor()
    if not ed:
        say("spark soul: no editor found -- set $EDITOR, or write %s by hand" % SOUL_FILE)
        return 1
    if not os.path.isfile(SOUL_FILE):
        t, source = read(cfg)
        write(cfg, t)
        say("ok     seeded       from the %s paragraph" % {"env": "SPARK_PERSONA_EXTRA",
                                                            "personality": "built-in and the personality"}.get(source, "built-in"))
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
        say("ok     soul         %d characters, over the cap, cut at %d" % (n, SOUL_MAX))
    elif n == 0:
        say("ok     soul         empty -- the built-in paragraph applies")
    else:
        say("ok     soul         %d characters, yours" % n)
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
        return _edit(cfg, core="--core" in args[1:])
    if args[0] == "reset":
        return _reset()
    say(SOUL_USAGE.rstrip())
    return 2
