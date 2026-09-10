# spark.site -- the site.env custodian and the machine-shape verbs:
# set_keys/apply (every choice lands through them), the rc-hook custody,
# `spark font`, `spark quiet`, `spark headless`, `spark client` (and
# `spark theme` in theme.py, `spark model`/`ember` in model.py, `spark
# shell` in shell.py). Each writes the key, then runs bootstrap.sh so the
# machine follows; editing site.env by hand and running bootstrap does
# the same thing.

import os
import pwd
import re
import subprocess
import sys
from urllib.parse import urlsplit

from . import CONFIG_DIR, HOME, IS_MAC, MARK, REPO, SITE_ENV, config, distro, glyph, is_wsl, say

# WSL 2: Linux, minus what the VT console and GRUB own (contract 8 lines)
WSL_NO_FONT = "no console on WSL 2: the font lives in Windows Terminal's settings"
WSL_NO_BOOT = "no GRUB on WSL 2: Windows boots it"
WSL_NO_BRAIN = "WSL 2 stops with its last window: not a brain (a Linux box is)"
# Arch: Linux, minus console-setup and update-grub (contract 8 lines)
ARCH_NO_FONT = "no console-setup on Arch: the console font is /etc/vconsole.conf's (FONT=), left alone in this version"
ARCH_NO_BOOT = "no update-grub on Arch: GRUB is left alone in this version"


def no_console_font():
    """The one line that says why this Linux's console font is not spark's
    to set ('' when it is): WSL 2 has no console, Arch no console-setup."""
    if IS_MAC:
        return ""
    if is_wsl():
        return WSL_NO_FONT
    if distro() == "arch":
        return ARCH_NO_FONT
    return ""


def no_grub():
    """The one line that says why quiet boot is not spark's to set here
    ('' when it is): WSL 2 has no GRUB, Arch no update-grub."""
    if IS_MAC:
        return ""
    if is_wsl():
        return WSL_NO_BOOT
    if distro() == "arch":
        return ARCH_NO_BOOT
    return ""


def set_keys(_file=None, _quiet=False, **kv):
    """Rewrite KEY= lines in site.env (or _file; append the missing ones);
    keep it 0600. One `ok site KEY=value` row per key unless _quiet."""
    path = _file or SITE_ENV
    lines = []
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        pass
    for key, val in kv.items():
        done = False
        for i, line in enumerate(lines):
            if line.startswith(key + "="):
                lines[i] = "%s=%s" % (key, val)
                done = True
        if not done:
            lines.append("%s=%s" % (key, val))
        if not _quiet:
            say("ok     %-12s %s=%s" % ("site" if path == SITE_ENV else "spark.env", key, val))
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(path, 0o600)


def apply(rows, stream=False):
    """Run bootstrap.sh and show the rows that matter for this change.
    stream=True at a terminal hands bootstrap the terminal unfiltered, so
    a model download shows curl's progress bar live; captured output (a
    pipe, a script) keeps the filtered rows either way. An empty rows shows
    every row that is not ok (the non-stream branch): a caller that does
    not know which rows changed, like `spark update`, wants everything
    bootstrap did.
    SPARK_NO_APPLY=1 (tests) writes the key only."""
    if os.environ.get("SPARK_NO_APPLY"):
        return 0
    cmd = ["sh", os.path.join(REPO, "bootstrap.sh")]
    if stream and sys.stdout.isatty():
        if subprocess.run(cmd).returncode != 0:
            say("spark: bootstrap.sh failed (the output above says where)")
            return 1
    else:
        p = subprocess.run(cmd, capture_output=True, text=True)
        if rows:
            pattern = r"^(ok|would|skip|todo)\s+(%s)\b" % "|".join(rows)
            for line in p.stdout.splitlines():
                if re.match(pattern, line):
                    say(line)
        else:
            for line in p.stdout.splitlines():
                if not re.match(r"^ok\s", line):
                    say(line)
        if p.returncode != 0:
            say("spark: bootstrap.sh failed:\n" + (p.stderr or p.stdout)[-800:])
            return 1
    from . import check
    check.refresh()
    return 0


# ------------------------------------------------------------------- font
# Core, not the shell layer: the console is the machine's face whether or
# not spark owns the shell (the Nerd Font download stays with the layer).
FONT_USAGE = """%s font -- the terminal's font

  spark font                    what is set
  spark font list               Linux: the console faces and sizes installed
                                (/usr/share/consolefonts); macOS: the
                                monospace faces installed here, by PostScript
                                name, and how to find any other
  spark font FACE SIZE          Linux console: a face and size from the list
                                (e.g. Terminus 16x32); macOS: an installed
                                font's PostScript name and points (13); one
                                face and size for every spark profile
  spark font none               Linux: leave the console's font alone
""" % MARK
# monospace faces a Mac may hold, by PostScript name: the list shows the installed ones
MAC_MONO = ("JetBrainsMonoNFM-Regular", "JetBrainsMono-Regular", "Menlo-Regular", "Monaco", "SFMono-Regular",
            "Courier", "CourierNewPSMT", "AndaleMono", "PTMono-Regular", "FiraCode-Regular", "Hack-Regular",
            "SourceCodePro-Regular", "CascadiaCode-Regular", "UbuntuMono-Regular", "DejaVuSansMono",
            "Inconsolata-Regular", "RobotoMono-Regular", "IBMPlexMono", "VictorMono-Regular")


# the monospace faces every Mac ships (/System/Library/Fonts, outside Spotlight's index)
MAC_SYSTEM = {"Menlo-Regular", "Menlo-Bold", "Monaco", "SFMono-Regular", "SFMono-Bold", "Courier", "Courier-Bold",
              "CourierNewPSMT", "AndaleMono"}


def mac_font_installed(face):
    """True for a face every Mac ships or one Spotlight finds (kMDItemFonts
    holds PostScript names, 20 ms); False when Spotlight indexes and has
    no such face; None when indexing is off, or not a Mac -- so a caller
    never refuses on no evidence."""
    if not IS_MAC:
        return None
    if face in MAC_SYSTEM:
        return True
    from . import run
    rc, out = run(["mdfind", "kMDItemFonts == '%s'" % face.replace("'", "")], timeout=5)
    if rc == 0 and out.strip():
        return True
    rc, out = run(["mdutil", "-s", "/"], timeout=5)
    return False if rc == 0 and "Indexing enabled" in out else None
CONSOLEFONTS_DIR = "/usr/share/consolefonts"
_FONT_FILE = re.compile(r"^[A-Za-z0-9]+-([A-Za-z]+?)(\d+(?:x\d+)?)\.psfu?(?:\.gz)?$")


NERDFONT_DIR = os.path.join(HOME, ".local", "share", "fonts", "JetBrainsMonoNerdFont")


def console_fonts():
    """{face: set of sizes} parsed from /usr/share/consolefonts file names
    (<codeset>-<Face><Size>.psf.gz -- the sizes there are HxW). {} when the
    directory is unreadable (then nothing can be validated)."""
    out = {}
    try:
        names = os.listdir(CONSOLEFONTS_DIR)
    except OSError:
        return {}
    for n in names:
        m = _FONT_FILE.match(n)
        if m:
            out.setdefault(m.group(1), set()).add(m.group(2))
    return out


def _size_spellings(size):
    """The file-name spellings one chosen size may match: as given, flipped
    (console-setup writes WxH, the font files say HxW), and the height
    alone (Fixed16.psf serves FONTSIZE=8x16)."""
    names = {size}
    if "x" in size:
        w, h = size.split("x", 1)
        names.add("%sx%s" % (h, w))
        names.add(h)
    return names


def font_list():
    """`spark font list`: what FACE SIZE may name here."""
    if IS_MAC:
        say("%s font list -- macOS: the monospace faces installed here, by PostScript name; the size is points" % MARK)
        notes = {"JetBrainsMonoNFM-Regular": "the Nerd Font spark installs (Brewfile): the default"}
        seen = 0
        for face in MAC_MONO:
            here = mac_font_installed(face)
            if here or (here is None and face in MAC_MONO[:5]):
                say("  %-28s %s" % (face, notes.get(face, "")))
                seen += 1
        if not seen:
            say("  (Spotlight has no font index here: Menlo-Regular, Monaco and SFMono-Regular are always on a Mac)")
        say("  any other: Font Book shows a font's PostScript name (select it, Cmd-I)")
        return 0
    fonts = console_fonts()
    if not fonts:
        say("%s font list -- nothing in %s (console-setup not installed?)" % (MARK, CONSOLEFONTS_DIR))
    else:
        say("%s font list -- the console faces in %s, sizes as spark font takes them (WxH)" % (MARK, CONSOLEFONTS_DIR))
        for face in sorted(fonts):
            sizes = sorted({size_as_taken(x) for x in fonts[face]}, key=lambda s: tuple(int(p) for p in s.split("x")[::-1]))
            say("  %-16s %s" % (face, " ".join(sizes)))
        say("  spark font FACE SIZE sets one, e.g. spark font Terminus 16x32")
    # the Nerd Font `spark shell on` installs is not one of these: the console
    # takes .psf faces, that one is a .ttf for a terminal emulator. Naming it
    # here is the only place the two meet.
    if os.path.isdir(NERDFONT_DIR):
        say("  JetBrainsMono Nerd Font is installed in ~%s" % NERDFONT_DIR[len(HOME):])
        say("  for your terminal emulator -- set it there; spark font is the console")
    return 0


def size_as_taken(file_size):
    """A font file's size the way spark font (console-setup's FONTSIZE)
    spells it: the files say HxW, or the height alone for an 8-wide face
    -- 32x16 is taken as 16x32, 16 as 8x16."""
    if "x" in file_size:
        h, w = file_size.split("x", 1)
        return "%sx%s" % (w, h)
    return "8x%s" % file_size


def cmd_font(args):
    if args and args[0] in ("-h", "--help", "help"):
        say(FONT_USAGE.rstrip())
        return 0
    cfg = config.load()
    why = no_console_font()
    if why:
        # show forms answer; set forms refuse: nothing is written for a
        # console spark does not manage here
        say("%s font -- %s" % (MARK, why))
        return 0 if not args or args[0] in ("status", "list") else 2
    if not args or args[0] == "status":
        if IS_MAC:
            say("%s font -- Terminal.app profile: %s %s   (spark theme profile applies it)" % (MARK, cfg.font_face, cfg.font_size))
        elif cfg.font_face:
            say("%s font -- console: %s %s" % (MARK, cfg.font_face, cfg.font_size))
        else:
            say("%s font -- console: not managed (SITE_FONT_FACE unset)" % MARK)
        return 0
    if args[0] == "list":
        return font_list()
    if args[0] == "none":
        set_keys(SITE_FONT_FACE="", SITE_FONT_SIZE="")
        say("the console keeps whatever font it has now")
        return 0
    if len(args) != 2:
        say(FONT_USAGE.rstrip())
        return 2
    face, size = args
    if IS_MAC:
        if not re.match(r"^\d+(\.\d+)?$", size) or not 6 <= float(size) <= 72:
            say("spark font: %s is not a size -- points on macOS, 6 to 72, e.g. 13" % size)
            return 2
        # refuse a face this Mac does not have (a console face such as VGA,
        # a typo): Terminal.app would fall back to its own font in silence
        if mac_font_installed(face) is False:
            say("spark font: no font named %s is installed here -- spark font list shows the monospace ones" % face)
            return 2
    else:
        if not re.match(r"^\d+(x\d+)?$", size):
            say("spark font: %s is not a size -- WxH on the Linux console, e.g. 16x32 (spark font list)" % size)
            return 2
        # refuse a face or size consolefonts does not hold, before anything
        # is written; an unreadable consolefonts dir validates nothing
        fonts = console_fonts()
        if fonts and face not in fonts:
            say("spark font: no console face named %s -- spark font list shows them" % face)
            return 2
        if fonts and not (_size_spellings(size) & fonts[face]):
            say("spark font: %s has no size %s -- spark font list shows them" % (face, size))
            return 2
    set_keys(SITE_FONT_FACE=face, SITE_FONT_SIZE=size)
    if IS_MAC:
        if os.environ.get("SPARK_NO_APPLY"):
            say("ok     font         %s %s written (SPARK_NO_APPLY: no profile)" % (face, size))
            return 0
        from . import theme
        return theme.profile(config.load(), False)
    return apply(["console", "font"])


# ------------------------------------------------------------------ quiet
QUIET_USAGE = """%s quiet -- what spark and the machine keep silent

  spark quiet                   the four states: start, login, boot, audio
  spark quiet start [on|off]    spark's own noise, both OSes: no login banner,
                                one-line serve and forge, one-line bare spark
  spark quiet login [on|off]    Linux: no distro notice, no kernel line
  spark quiet boot [on|off]     Linux: straight past GRUB's menu
  spark quiet audio [on|off]    both OSes: no sound from spark (the audio row
                                says which player it would use)
""" % MARK
QUIET_KEYS = {"start": "SITE_QUIET_START", "login": "SITE_QUIET_LOGIN", "boot": "SITE_QUIET_BOOT",
              "audio": "SITE_QUIET_AUDIO"}
MAC_NO_QUIET = "macOS: no motd, no GRUB"


def _quiet_state(cfg, sub):
    return "on" if {"start": cfg.quiet_start, "login": cfg.quiet_login, "boot": cfg.quiet_boot,
                    "audio": cfg.quiet_audio}[sub] else "off"


def cmd_quiet(args):
    if args and args[0] in ("-h", "--help", "help"):
        say(QUIET_USAGE.rstrip())
        return 0
    cfg = config.load()
    if not args or args[0] == "status":
        start, audio = _quiet_state(cfg, "start"), _quiet_state(cfg, "audio")
        if IS_MAC:
            say("%s quiet -- start %s, audio %s (login, boot: macOS has no motd, no GRUB)" % (MARK, start, audio))
        elif not cfg.shell:
            say("%s quiet -- start %s, audio %s (login, boot: the shell layer is off)" % (MARK, start, audio))
        else:
            say("%s quiet -- start %s, login %s, boot %s, audio %s" % (
                MARK, start, _quiet_state(cfg, "login"), "n/a (%s)" % no_grub() if no_grub() else _quiet_state(cfg, "boot"), audio))
        return 0
    sub = args[0]
    if sub not in QUIET_KEYS or len(args) > 2 or (len(args) == 2 and args[1] not in ("on", "off")):
        say(QUIET_USAGE.rstrip())
        return 2
    linux_only = sub in ("login", "boot")                  # start and audio are both OSes, core
    no_boot = no_grub() if sub == "boot" else ""             # login (motd) is real on WSL and Arch; GRUB is not spark's there
    if len(args) == 1:                                     # show one state
        if linux_only and IS_MAC:
            say("%s quiet %s -- %s" % (MARK, sub, MAC_NO_QUIET))
            return 0
        if no_boot:
            say("%s quiet %s -- %s" % (MARK, sub, no_boot))
            return 0
        if linux_only and not cfg.shell:
            say("%s quiet %s -- the shell layer is off (spark shell on)" % (MARK, sub))
            return 0
        say("%s quiet %s -- %s" % (MARK, sub, _quiet_state(cfg, sub)))
        return 0
    if linux_only and IS_MAC:                              # nothing to set there
        say("%s quiet %s -- %s" % (MARK, sub, MAC_NO_QUIET))
        return 2
    if no_boot:
        say("%s quiet %s -- %s" % (MARK, sub, no_boot))
        return 2
    from . import shell
    if linux_only and shell.shell_off("quiet"):
        return 2
    set_keys(**{QUIET_KEYS[sub]: "yes" if args[1] == "on" else "no"})
    if sub == "audio":
        # the key is the behavior: what spark plays reads it at start
        say("audio is %s" % ("quiet: spark plays no sound" if args[1] == "on" else "on: the sounds spark has play again"))
        from . import check
        check.refresh()
        return 0
    if sub == "start":
        # the key is the behavior: nothing on disk to converge, no bootstrap row
        say("start is %s" % ("quiet: no login banner, one line from serve, forge and bare spark"
                             if args[1] == "on" else "loud again: the banner and the full narration are back"))
        from . import check
        check.refresh()
        return 0
    return apply(["quiet-" + sub])


# --------------------------------------------------------------- headless
HEADLESS_USAGE = """%s headless -- a machine that is the brain

  spark headless                what is set, and what is in effect here
  spark headless on             the FORGE up from boot, nobody logged in, never
                                asleep. Linux: linger, the render group, sleep
                                masked, the lid ignored. macOS: LaunchDaemons in
                                system/, pmset never sleeps, wake on LAN
  spark headless off            a workstation again (macOS: pmset untouched)
""" % MARK
HEADLESS_ROWS = ["headless", "linger", "render", "sleep", "lid", "daemons", r"spark\.(serve|forge|check)"]
SLEEP_TARGETS = ("sleep.target", "suspend.target", "hibernate.target", "hybrid-sleep.target")
LOGIND_DROPIN = "/etc/systemd/logind.conf.d/spark.conf"
PMSET_WANT = (("sleep", "0"), ("disksleep", "0"), ("womp", "1"), ("autorestart", "1"))


def headless_facts(cfg):
    """What is in effect on this machine, read-only: [(piece, good, detail)].
    The check row and `spark headless` read it; bootstrap.sh changes it."""
    from . import engine, run
    facts = []
    if IS_MAC:
        for unit, wanted in (("serve", cfg.service == "auto"), ("forge", cfg.forge != "off"), ("check", True)):
            dom = engine.service_domain(cfg, unit)
            facts.append(("%s daemon" % unit, dom == "system" or not wanted,
                          "system/ (from boot)" if dom == "system" else ("gui/ (a login agent)" if engine.service_state(cfg, unit) == "loaded" else "absent")))
        rc, out = run(["pmset", "-g"], timeout=10)
        pm = {}
        for line in out.splitlines():
            f = line.split()
            if len(f) >= 2:
                pm[f[0]] = f[1]
        for key, want in PMSET_WANT:
            cur = pm.get(key)
            good = cur is None or cur == want
            facts.append(({"sleep": "never sleeps", "disksleep": "disks stay awake", "womp": "wake on LAN",
                           "autorestart": "restarts after power loss"}[key], good,
                          "pmset %s %s" % (key, cur if cur is not None else "(not on this hardware)")))
        return facts
    rc, out = run(["loginctl", "show-user", os.environ.get("USER") or cfg.user, "-p", "Linger", "--value"], timeout=10)
    facts.append(("linger", out.strip() == "yes", "units run from boot" if out.strip() == "yes" else "units stop at logout"))
    if os.path.exists("/dev/dri/renderD128"):
        rc, out = run(["id", "-nG"], timeout=10)
        member = "render" in out.split()
        facts.append(("render group", member, "the units see the GPU from boot" if member else "the GPU needs a login session"))
    masked = []
    for t in SLEEP_TARGETS:
        rc, out = run(["systemctl", "is-enabled", t], timeout=10)
        if out.strip() == "masked":
            masked.append(t)
    facts.append(("sleep masked", len(masked) == len(SLEEP_TARGETS), "%d of %d targets masked" % (len(masked), len(SLEEP_TARGETS))))
    try:
        with open(LOGIND_DROPIN, encoding="utf-8") as f:
            lid = "HandleLidSwitch=ignore" in f.read()
    except OSError:
        lid = False
    facts.append(("lid ignored", lid, LOGIND_DROPIN if lid else "no logind drop-in"))
    return facts


def cmd_headless(args):
    cfg = config.load()
    if args and args[0] in ("-h", "--help", "help"):
        say(HEADLESS_USAGE.rstrip())
        return 0
    if not args or args[0] == "status":
        say("%s headless -- SITE_HEADLESS=%s: %s" % (MARK, "yes" if cfg.headless else "no",
                                                    "a brain (the FORGE up from boot, never asleep)" if cfg.headless
                                                    else "a workstation (spark headless on for a brain)"))
        for piece, good, detail in headless_facts(cfg):
            say("  %s %-26s %s" % (glyph("ok") if good else ("!" if cfg.headless else glyph("na")), piece, detail))
        return 0
    if args[0] not in ("on", "off"):
        say(HEADLESS_USAGE.rstrip())
        return 2
    if args[0] == "on" and not IS_MAC and is_wsl():
        say("%s headless -- %s" % (MARK, WSL_NO_BRAIN))
        return 2
    set_keys(SITE_HEADLESS="yes" if args[0] == "on" else "no")
    if args[0] == "off":
        os.environ["SPARK_HEADLESS_UNDO"] = "1"    # only this verb unmasks sleep and frees the lid
    return apply(HEADLESS_ROWS)


# ----------------------------------------------------------------- client
CLIENT_USAGE = """%s client -- a machine that answers from another machine's FORGE

  spark client                  what is set here, and whether the peer answers
  spark client URL              answer from the FORGE at URL: no model, no
                                engine, nothing runs here; the prompt, chat and
                                explain do (spark user add NAME on the other
                                machine mints your token, spark user login
                                NAME here presents it)
  spark client off              serve here again: spark model auto picks one
""" % MARK


def cmd_client(args):
    from . import users, wire
    cfg = config.load()
    if args and args[0] in ("-h", "--help", "help"):
        say(CLIENT_USAGE.rstrip())
        return 0
    if not args or args[0] == "status":
        if not cfg.client:
            say("%s client -- not a client: SITE_AI_MODEL=%s, SITE_PEER_AI_URL=%s" % (
                MARK, cfg.model_choice, cfg.peer_ai_url or "unset"))
            say("  spark client URL answers from another machine's FORGE, nothing served here")
            return 0
        say("%s client -- of %s (SITE_AI_MODEL=none: nothing runs here)" % (MARK, cfg.peer_ai_url))
        fh = wire.forge_health(cfg.peer_ai_url)
        if isinstance(fh, dict):
            up = fh.get("upstream", "down")
            peer = "forge %s%s" % ("ok, " + fh.get("model", "?") if up == "ok" else "up, its model " + up, "")
        else:
            peer = "down" if fh == "down" else "server " + wire.health(cfg.peer_ai_url)
        say("  %s %-12s %s" % (glyph("ok") if "ok" in peer else "!", "peer", peer))
        me = users.account()[0]
        say("  %s %-12s %s" % (glyph("ok") if me else "!", "account",
                               "this machine is %s" % me if me else "no login -- " + _login_hint(cfg.peer_ai_url)))
        return 0
    if args[0] == "off":
        # the one deliberate promotion: the client shape ends here, then
        # `spark model auto` runs as on any server (cmd_model refuses a
        # choice while the shape holds)
        say("the peer stays first while it answers; this machine's own model is the fallback")
        set_keys(SITE_AI_MODEL="auto")
        from . import model
        return model.cmd_model(["auto"])
    url = args[0].rstrip("/")
    if not re.match(r"^https?://[^/\s]+$", url):
        say("%s client -- URL is http://host:port, the FORGE's (spark forge --print-client there)" % MARK)
        return 2
    set_keys(SITE_PEER_AI_URL=url, SITE_AI_MODEL="none")
    rc = apply(["configs", "rc", "engine", "model", "services", "token"])
    if rc == 0:
        if not users.account()[0]:
            say("then log in as yourself: " + _login_hint(url))
        from . import engine
        if engine.server_pids(cfg.port):
            say("the server that ran here keeps running: spark serve off ends it")
    return rc


def _login_hint(url):
    host = urlsplit(url).hostname or url
    return "spark user add NAME on %s (the token shows once), then spark user login NAME here" % host


# --------------------------------------------------------------------- rc
# The core rc hook: bootstrap's `rc` row appends one marked line to the
# login shell's rc file; `spark shell on` may replace that file with spark's
# own symlink; `spark shell off` hands it back (restore_rc). Pure functions:
# the callers print the rows.
RC_MARKER = "config/spark/hook."
RC_LINE = {"bash": "[ -r ~/.config/spark/hook.bash ] && . ~/.config/spark/hook.bash   # spark: the AI at the prompt",
           "zsh": "[[ -r ~/.config/spark/hook.zsh ]] && source ~/.config/spark/hook.zsh   # spark: the AI at the prompt"}
RC_FILES = (".zshrc", ".zprofile") if IS_MAC else (".bashrc", ".bash_profile")


def login_shell():
    """The login shell's basename: $SHELL, else the passwd entry."""
    s = os.environ.get("SHELL") or ""
    if not s:
        try:
            s = pwd.getpwuid(os.getuid()).pw_shell
        except KeyError:
            s = ""
    return os.path.basename(s) or "sh"


def rc_file(shell):
    """The rc file the `rc` row hooks for this shell (bash, zsh), else None."""
    name = {"bash": ".bashrc", "zsh": ".zshrc"}.get(shell)
    return os.path.join(HOME, name) if name else None


def _spark_link(path):
    """True when path is a symlink into the repository (spark's own file)."""
    if not os.path.islink(path):
        return False
    try:
        target = os.readlink(path)
    except OSError:
        return False
    return target.startswith(REPO + "/") or os.path.realpath(path).startswith(os.path.realpath(REPO) + "/")


def rc_hook_state(shell):
    """("link" | "hook" | "missing", path): the rc file is spark's own
    symlink, sources the hook (the marker line), or lacks it (path None
    for a shell without an rc file to hook)."""
    path = rc_file(shell)
    if not path:
        return ("missing", None)
    if _spark_link(path):
        return ("link", path)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            if RC_MARKER in f.read():
                return ("hook", path)
    except OSError:
        pass
    return ("missing", path)


def restore_rc():
    """spark shell off: every rc file of this OS that is spark's symlink goes
    back to the user -- the link removed, <file>.bak moved back when it
    exists, else the file is gone (that was the pre-spark state). An empty
    ~/.bash_profile is a trap, not a restore: a bash login shell stops
    there and ~/.profile -- the one that sources ~/.bashrc and the hook --
    never runs, so spark vanishes from a console login. The rc row
    recreates ~/.bashrc with the hook line right after. Returns
    [(path, what)]."""
    done = []
    for name in RC_FILES:
        path = os.path.join(HOME, name)
        if not _spark_link(path):
            continue
        os.unlink(path)
        bak = path + ".bak"
        if os.path.lexists(bak):
            os.rename(bak, path)
            done.append((path, "restored from %s.bak" % name))
        else:
            done.append((path, "removed (no %s.bak: there was no file before)" % name))
    return done


def main(sub, args):
    if sub == "headless":
        return cmd_headless(args)
    if sub == "client":
        return cmd_client(args)
    return cmd_font(args) if sub == "font" else cmd_quiet(args)
