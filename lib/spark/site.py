# spark.site -- the site.env custodian and the machine-shape verbs:
# set_keys/apply (every choice lands through them), the rc-hook custody,
# `spark font`, `spark quiet`, `spark headless`, `spark client` (and
# `spark theme` in theme.py, `spark model`/`ember` in model.py). Each
# writes the key, then runs bootstrap.sh so the machine follows; editing
# site.env by hand and running bootstrap does the same thing.

import gzip
import os
import pwd
import re
import struct
import subprocess
import sys
from urllib.parse import urlsplit

from . import (CONFIG_DIR, HOME, IS_MAC, MARK, REPO, SHARE_TOKEN, SHARE_URL, SITE_ENV, SPARK_ENV, TOKEN_FILE,
               config, distro, glyph, is_wsl, say)

# WSL 2: Linux, minus what the VT console and GRUB own (contract 8 lines)
WSL_NO_FONT = "no console on WSL 2: the font lives in Windows Terminal's settings"
WSL_NO_BOOT = "no GRUB on WSL 2: Windows boots it"
WSL_NO_BRAIN = "WSL 2 stops with its last window: it cannot stay on and answer (a Linux machine can)"
# a Linux with neither console mechanism (contract 8 line); Arch keeps
# only the kernel-line refusal, and only without a Unified Kernel Image
NO_CONSOLE_FONT = "no console-setup and no vconsole.conf here: the console font is not spark's to set"
ARCH_NO_BOOT = ("no UKI on this Arch: the kernel line is the boot loader's "
                "(a loader entry's options line, or GRUB_CMDLINE_LINUX_DEFAULT then grub-mkconfig)")
# the quiet kernel line, the same seven words on every shape (bootstrap.sh
# QUIET_WORDS is the sh twin): quiet+loglevel=3 silence the kernel, splash
# hands Plymouth the boot when it is installed (inert otherwise),
# systemd.show_status=false keeps the Started/Stopping lines off the
# console at boot and shutdown, udev.log_level=3 quiets the initramfs,
# vt.global_cursor_default=0 the early cursor, fbcon=nodefer the flicker
QUIET_WORDS = "quiet splash loglevel=3 systemd.show_status=false udev.log_level=3 vt.global_cursor_default=0 fbcon=nodefer"
# the one drop-in spark owns on an Arch UKI: mkinitcpio embeds every
# /etc/cmdline.d/*.conf after /etc/kernel/cmdline (zz- sorts it last)
CMDLINE_DROPIN = os.environ.get("SPARK_ETC_CMDLINE_DROPIN", "/etc/cmdline.d/zz-spark-quiet.conf")
SPLASH_MARK = "#spark-quiet# "


def mkinitcpio_d():
    return os.environ.get("SPARK_ETC_MKINITCPIO_D", "/etc/mkinitcpio.d")


def boot_shape():
    """How this Linux gets its kernel line, root-free: `uki` when a
    mkinitcpio preset builds a Unified Kernel Image (an uncommented
    `<preset>_uki=` line: the cmdline is /etc/kernel/cmdline plus
    /etc/cmdline.d/*.conf, the splash the preset's --splash), `grub` when
    /etc/default/grub is here, else ''. SPARK_ETC_MKINITCPIO_D pins the
    preset dir in tests."""
    if IS_MAC or is_wsl():
        return ""
    try:
        names = sorted(n for n in os.listdir(mkinitcpio_d()) if n.endswith(".preset"))
    except OSError:
        names = []
    for name in names:
        try:
            with open(os.path.join(mkinitcpio_d(), name), encoding="utf-8", errors="replace") as f:
                if re.search(r"^[a-z_]+_uki=", f.read(), re.M):
                    return "uki"
        except OSError:
            continue
    return "grub" if os.path.isfile("/etc/default/grub") else ""


def splash_live():
    """True while a mkinitcpio preset still embeds a splash (an unmarked
    `*_options=... --splash` line): the logo is on the next image."""
    try:
        names = sorted(n for n in os.listdir(mkinitcpio_d()) if n.endswith(".preset"))
    except OSError:
        return False
    for name in names:
        try:
            with open(os.path.join(mkinitcpio_d(), name), encoding="utf-8", errors="replace") as f:
                if re.search(r"^[a-z_]+_options=.*--splash", f.read(), re.M):
                    return True
        except OSError:
            continue
    return False


# the two files a Linux sets its console font in, seamed for the tests
CONSOLE_SETUP = os.environ.get("SPARK_ETC_CONSOLE_SETUP", "/etc/default/console-setup")
VCONSOLE = os.environ.get("SPARK_ETC_VCONSOLE", "/etc/vconsole.conf")


def console_shape():
    """How this Linux sets its console font, root-free and by mechanism,
    never by family: `setup` when console-setup's file is here (Debian:
    FONTFACE and FONTSIZE, composed from /usr/share/consolefonts),
    `vconsole` when /etc/vconsole.conf is (Arch, and every systemd distro
    without console-setup: FONT= names one of the kbd font files), ''
    when neither. bootstrap's console row is the sh twin."""
    if IS_MAC or is_wsl():
        return ""
    if os.path.isfile(CONSOLE_SETUP):
        return "setup"
    if os.path.isfile(VCONSOLE):
        return "vconsole"
    return ""


def no_console_font():
    """The one line that says why this Linux's console font is not spark's
    to set ('' when it is): WSL 2 has no console; a Linux with neither
    console-setup nor vconsole.conf has no file to write."""
    if IS_MAC:
        return ""
    if is_wsl():
        return WSL_NO_FONT
    if not console_shape():
        return NO_CONSOLE_FONT
    return ""


def no_grub():
    """The one line that says why quiet boot is not spark's to set here
    ('' when it is): WSL 2 has no GRUB; Arch has no update-grub, so only
    a Unified Kernel Image (a cmdline.d drop-in) is spark's there."""
    if IS_MAC:
        return ""
    if is_wsl():
        return WSL_NO_BOOT
    if distro() == "arch" and boot_shape() != "uki":
        return ARCH_NO_BOOT
    return ""


def set_keys(_file=None, _quiet=False, **kv):
    """Rewrite KEY= lines in site.env (or _file; append the missing ones);
    keep it 0600. One `ok site KEY=value` row per key unless _quiet.
    A value contract 3 would refuse is refused HERE: written, it poisons
    the whole file and every verb dies with exit 2 before its help."""
    for key, val in kv.items():
        bad = re.search(r"[;`$()|&<>]", str(val))
        if bad:
            raise ValueError("%s: a config value cannot hold %s (contract 3)" % (key, bad.group(0)))
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
# The console is the machine's face: its font is spark's to set (a
# terminal emulator's font is set in the emulator).
FONT_USAGE = """%s font -- the terminal's font

  spark font                    what is set
  spark font list               Linux: the console fonts installed here, as
                                FACE and size (console-setup's faces, or the
                                kbd font files); macOS: the monospace faces
                                installed, by PostScript name
  spark font FACE SIZE          Linux console: a face and size from the list
                                (Terminus 16x32; Lat2-Terminus16 8x16);
                                macOS: an installed font's PostScript name
                                and points (13); one face and size for every
                                spark profile
  spark font none               the console keeps whatever font it has
""" % MARK
# monospace faces a Mac may hold, by PostScript name: the list shows the installed ones
MAC_MONO = ("Menlo-Regular", "Monaco", "SFMono-Regular", "JetBrainsMono-Regular", "Courier",
            "CourierNewPSMT", "AndaleMono", "PTMono-Regular", "FiraCode-Regular", "Hack-Regular",
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
    seam = os.environ.get("SPARK_MAC_FONTS")          # the fixture's installed faces, colon-separated
    if seam is not None:
        return face in seam.split(":")
    if face in MAC_SYSTEM:
        return True
    from . import run
    rc, out = run(["mdfind", "kMDItemFonts == '%s'" % face.replace("'", "")], timeout=5)
    if rc == 0 and out.strip():
        return True
    rc, out = run(["mdutil", "-s", "/"], timeout=5)
    return False if rc == 0 and "Indexing enabled" in out else None


# where a Linux keeps its console fonts: kbd's dir (Arch, Fedora), then
# console-setup's (Debian); SPARK_CONSOLEFONTS_DIR pins one in tests
CONSOLEFONTS_DIRS = ("/usr/share/kbd/consolefonts", "/usr/share/consolefonts")
_COMPOSED_FILE = re.compile(r"^[A-Za-z0-9]+-([A-Za-z]+?)(\d+(?:x\d+)?)\.psfu?(?:\.gz)?$")   # console-setup: <codeset>-<Face><Size>
_PSF_FILE = re.compile(r"^(.+?)\.psfu?(?:\.gz)?$")


def consolefonts_dir():
    want = os.environ.get("SPARK_CONSOLEFONTS_DIR")
    for d in ((want,) if want else CONSOLEFONTS_DIRS):
        if os.path.isdir(d):
            return d
    return ""


def psf_size(path):
    """A console font file's cell as WxH, from its own header (gzip or
    plain): PSF1 (magic 36 04) is 8 wide with the height in byte 3; PSF2
    (magic 72 b5 4a 86) keeps the height at offset 24 and the width at
    28, little-endian. '' for anything else."""
    try:
        opener = gzip.open if path.endswith(".gz") else open
        with opener(path, "rb") as f:
            head = f.read(32)
    except (OSError, EOFError):
        return ""
    if head[:2] == b"\x36\x04" and len(head) >= 4:
        return "8x%d" % head[3]
    if head[:4] == b"\x72\xb5\x4a\x86" and len(head) >= 32:
        h, w = struct.unpack("<II", head[24:32])
        return "%dx%d" % (w, h)
    return ""


def console_fonts():
    """{face: set of sizes}, every size the way spark font takes it (WxH).
    On the console-setup shape a face is what console-setup composes,
    parsed from the file names (<codeset>-<Face><Size>, the sizes there
    HxW -- size_as_taken flips them); on the vconsole shape a face is a
    font file's stem and its size comes from the file's own header. {} when
    the directory is unreadable (then nothing can be validated)."""
    d = consolefonts_dir()
    try:
        names = os.listdir(d) if d else []
    except OSError:
        return {}
    composed = console_shape() == "setup"
    out = {}
    for n in names:
        if composed:
            m = _COMPOSED_FILE.match(n)
            if m:
                out.setdefault(m.group(1), set()).add(size_as_taken(m.group(2)))
        else:
            m = _PSF_FILE.match(n)
            size = psf_size(os.path.join(d, n)) if m else ""
            if size:
                out.setdefault(m.group(1), set()).add(size)
    return out


def _size_key(size):
    return tuple(int(p) for p in size.split("x")[::-1])


def font_file():
    """The file a chosen console font is written into on this Linux."""
    return CONSOLE_SETUP if console_shape() == "setup" else VCONSOLE


def font_list():
    """`spark font list`: what FACE SIZE may name here."""
    if IS_MAC:
        say("%s font list -- macOS: the monospace faces installed here, by PostScript name; the size is points" % MARK)
        notes = {"Menlo-Regular": "the default: every Mac ships it"}
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
        say("%s font list -- no console font files under %s" % (MARK, consolefonts_dir() or " or ".join(CONSOLEFONTS_DIRS)))
    else:
        say("%s font list -- the console fonts in %s, as spark font takes them: FACE and WxH" % (MARK, consolefonts_dir()))
        for face in sorted(fonts):
            say("  %-24s %s" % (face, " ".join(sorted(fonts[face], key=_size_key))))
        say("  spark font FACE SIZE sets one: it lands in %s" % font_file())
    # a terminal emulator's face (a .ttf) is never one of these: the console
    # takes .psf faces; the emulator's font is set in the emulator
    say("  a terminal emulator's font is set in the emulator; spark font is the console")
    return 0


def size_as_taken(file_size):
    """A composed font file's size the way spark font (console-setup's
    FONTSIZE) spells it: the files say HxW, or the height alone for an
    8-wide face -- 32x16 is taken as 16x32, 16 as 8x16."""
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
            say("%s font -- console: %s %s (%s)" % (MARK, cfg.font_face, cfg.font_size, font_file()))
        else:
            say("%s font -- console: not managed (SITE_FONT_FACE unset; %s keeps its font)" % (MARK, font_file()))
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
        if not re.match(r"^\d+x\d+$", size):
            say("spark font: %s is not a size -- WxH on the Linux console, e.g. 16x32 (spark font list)" % size)
            return 2
        # refuse a face or size the font files do not hold, before anything
        # is written; an unreadable fonts dir validates nothing
        fonts = console_fonts()
        if fonts and face not in fonts:
            say("spark font: no console font named %s -- spark font list shows them" % face)
            return 2
        if fonts and size not in fonts[face]:
            say("spark font: %s comes in %s, not %s -- spark font list" % (face, " ".join(sorted(fonts[face], key=_size_key)), size))
            return 2
    set_keys(SITE_FONT_FACE=face, SITE_FONT_SIZE=size)
    if IS_MAC:
        if os.environ.get("SPARK_NO_APPLY"):
            say("ok     font         %s %s written (SPARK_NO_APPLY: no profile)" % (face, size))
            return 0
        from . import theme
        return theme.profile(config.load(), False)
    return apply(["console"])


# ------------------------------------------------------------------ quiet
QUIET_USAGE = """%s quiet -- what spark and the machine keep silent

  spark quiet                   the four states: start, login, boot, audio
  spark quiet start [on|off]    spark's own noise, both OSes: no login banner,
                                one-line serve and forge, one-line bare spark
  spark quiet login [on|off]    Linux: no distro notice, no kernel line
  spark quiet boot [on|off]     Linux: straight past the boot menu, a silent
                                kernel line (GRUB, or an Arch kernel image)
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
        say("%s quiet %s -- %s" % (MARK, sub, _quiet_state(cfg, sub)))
        return 0
    if linux_only and IS_MAC:                              # nothing to set there
        say("%s quiet %s -- %s" % (MARK, sub, MAC_NO_QUIET))
        return 2
    if no_boot:
        say("%s quiet %s -- %s" % (MARK, sub, no_boot))
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
HEADLESS_USAGE = """%s headless -- the machine that stays on and answers

  spark headless                what is set, and what is in effect here
  spark headless on             the page's server up from boot, nobody logged
                                in, never asleep. Linux: linger, the render
                                group, sleep masked, the lid ignored. macOS:
                                LaunchDaemons in system/, pmset never sleeps,
                                wake on LAN
  spark headless off            under your login again (macOS: pmset untouched)
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
                                                    "stays on and answers (the page's server up from boot, never asleep)" if cfg.headless
                                                    else "under your login (spark headless on makes it stay on and answer)"))
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


# ------------------------------------------------------------------ share
SHARE_USAGE = """%s share -- one engine, shared with this machine's other OS users

  spark share                what is set, and what is in effect here
  spark share on             let a `spark` OS group read the api-token, so a
                             group member's spark answers from this machine's
                             engine as a client -- their own soul and memory,
                             one model loaded once for everyone
  spark share off            the shared token goes; the engine is yours again

  another OS user joins once, then logs in again:  sudo gpasswd -a NAME spark
  then, as them:  spark client URL   (spark share prints the URL)
""" % MARK
SHARE_ROWS = ["share"]


def no_share():
    """Why a shared engine is not this machine's to set here ('' when it
    is): macOS keeps one user per box in this version, WSL 2 is not a brain."""
    if IS_MAC:
        return "one user per machine on macOS in this version -- a shared engine is a Linux story"
    if is_wsl():
        return WSL_NO_BRAIN
    return ""


def _token_fresh(copy, source):
    """Is the shared copy current? By mtime, not contents: the owner is not
    in the spark group and cannot read the 0640 copy, so a content compare
    would false-alarm. The copy is fresh when it is no older than the source
    (spark share on stamps it after any token change). Unknown source (a
    user with no token of their own) is not our concern -- treat as fresh."""
    try:
        return os.stat(copy).st_mtime >= os.stat(source).st_mtime
    except OSError:
        return True


def _share_url():
    """The engine URL a local user points `spark client` at: the published
    /etc/spark/url, else whatever serve bound, else a placeholder."""
    from . import wire
    try:
        with open(SHARE_URL, encoding="utf-8") as f:
            url = f.read().strip()
            if url:
                return url
    except OSError:
        pass
    return wire.serve_url() or "http://<this-host>:8080"


def share_facts(cfg):
    """Read-only: [(piece, good, detail)] -- the group and the shared token,
    whether its perms are right and it still matches the live api-token.
    The verb's status and the check row both read it."""
    why = no_share()
    if why:
        return [("shared engine", not cfg.share, why)]
    import grp
    facts = []
    try:
        mem = grp.getgrnam("spark").gr_mem
        facts.append(("spark group", True, "%d member%s%s" % (len(mem), "" if len(mem) == 1 else "s",
                                                              (": " + ", ".join(mem)) if mem else "")))
    except KeyError:
        facts.append(("spark group", not cfg.share, "not created (spark share on)"))
    if os.path.exists(SHARE_TOKEN):
        try:
            st = os.stat(SHARE_TOKEN)
            mode = oct(st.st_mode & 0o777)[-3:]
            gname = grp.getgrgid(st.st_gid).gr_name
        except (OSError, KeyError):
            mode, gname = "???", "?"
        perms = mode == "640" and gname == "spark"
        stale = not _token_fresh(SHARE_TOKEN, TOKEN_FILE)
        facts.append(("shared token", perms and not stale, "%s (%s %s)%s" % (SHARE_TOKEN, mode, gname,
                      " -- STALE, spark share on re-syncs" if stale else "")))
    else:
        facts.append(("shared token", not cfg.share, "%s absent" % SHARE_TOKEN))
    if os.path.exists(SHARE_URL):
        try:
            url = open(SHARE_URL, encoding="utf-8").read().strip()
        except OSError:
            url = "?"
        facts.append(("engine url", bool(url), "%s (%s)" % (SHARE_URL, url or "empty")))
    else:
        facts.append(("engine url", not cfg.share, "%s absent (spark serve, then spark share on)" % SHARE_URL))
    return facts


def cmd_share(args):
    cfg = config.load()
    if args and args[0] in ("-h", "--help", "help"):
        say(SHARE_USAGE.rstrip())
        return 0
    if not args or args[0] == "status":
        say("%s share -- SITE_SHARE=%s: %s" % (MARK, "yes" if cfg.share else "no",
            "this box's engine is shared with its other OS users" if cfg.share
            else "not shared (spark share on lets the spark group in)"))
        for piece, good, detail in share_facts(cfg):
            say("  %s %-14s %s" % (glyph("ok") if good else ("!" if cfg.share else glyph("na")), piece, detail))
        if cfg.share and not no_share():
            say("  a user joins:  sudo gpasswd -a NAME spark  (log in again), then  spark client %s" % _share_url())
        return 0
    if args[0] not in ("on", "off"):
        say(SHARE_USAGE.rstrip())
        return 2
    why = no_share()
    if args[0] == "on" and why:
        say("%s share -- %s" % (MARK, why))
        return 2
    set_keys(SITE_SHARE="yes" if args[0] == "on" else "no")
    return apply(SHARE_ROWS)


# ----------------------------------------------------------------- client
CLIENT_USAGE = """%s client -- a client of another machine's server

  spark client                  what is set here, and whether the other
                                machine answers
  spark client URL              answer from the server at URL: no model, no
                                engine, nothing runs here; the prompt, chat and
                                explain do (spark user add NAME on the other
                                machine mints your token, spark user login
                                NAME here presents it)
  spark client off              serve here again: spark model auto picks one

  the URL may be this same machine's engine (spark share on there): a group
  member reads its shared token and answers from it, keeping their own
  soul and memory -- no second model loaded.
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
            say("  spark client URL answers from another machine's server, nothing served here")
            return 0
        say("%s client -- of %s (SITE_AI_MODEL=none: nothing runs here)" % (MARK, cfg.peer_ai_url))
        fh = wire.forge_health(cfg.peer_ai_url)
        if isinstance(fh, dict):
            up = fh.get("upstream", "down")
            peer = "page's server %s%s" % ("ok, " + fh.get("model", "?") if up == "ok" else "up, its model " + up, "")
        else:
            peer = "down" if fh == "down" else "engine " + wire.health(cfg.peer_ai_url)
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
        say("%s client -- URL is http://host:port, the other machine's server (spark forge --print-client there)" % MARK)
        return 2
    set_keys(SITE_PEER_AI_URL=url, SITE_AI_MODEL="none")
    if not cfg.get("SPARK_API_KEY_FILE", "") and os.access(SHARE_TOKEN, os.R_OK):
        # a shared engine on this box: use its group-readable token rather
        # than mint one of our own (which the engine would not accept)
        set_keys(_file=SPARK_ENV, SPARK_API_KEY_FILE=SHARE_TOKEN)
        say("using this machine's shared engine token (%s)" % SHARE_TOKEN)
    rc = apply(["configs", "rc", "engine", "model", "services", "token"])
    if rc == 0:
        if not users.account()[0]:
            say("then log in as yourself: " + _login_hint(url))
        from . import engine
        # a machine that served: the unit would bring the engine back at
        # boot, and spark serve off refuses while it is loaded -- stop
        # and disable it here, remove its links, and say so
        stopped = False
        name = engine.unit_name("serve")
        if IS_MAC:
            plist = os.path.join(HOME, "Library", "LaunchAgents", name + ".plist")
            if engine.service_state(cfg) == "loaded" or os.path.exists(plist):
                subprocess.run(["launchctl", "bootout", "gui/%d/%s" % (os.getuid(), name)], capture_output=True)
                stopped = True
            if os.path.exists(plist):
                os.remove(plist)
        else:
            link = os.path.join(HOME, ".config", "systemd", "user", name)
            if engine.service_state(cfg) == "loaded" or os.path.lexists(link):
                engine.sysctl(["disable", "--now", name])
                stopped = True
            if os.path.lexists(link):
                os.remove(link)
                engine.sysctl(["daemon-reload"])
        pids = engine.server_pids(cfg.port)
        if pids:
            engine.terminate(pids)
            left = engine.wait_gone(pids, 15)
            if left:
                engine.terminate(left, force=True)
            stopped = True
        if stopped:
            engine.forget()
            say("the engine that ran here is stopped")
    return rc


def _login_hint(url):
    host = urlsplit(url).hostname or url
    return "spark user add NAME on %s (the token shows once), then spark user login NAME here" % host


# --------------------------------------------------------------------- rc
# The rc hook: bootstrap's `rc` row appends one marked line to the login
# shell's rc file -- yours, a file or a symlink alike. Pure functions:
# the callers print the rows.
RC_MARKER = "config/spark/hook."
RC_LINE = {"bash": "[ -r ~/.config/spark/hook.bash ] && . ~/.config/spark/hook.bash   # spark: the AI at the prompt",
           "zsh": "[[ -r ~/.config/spark/hook.zsh ]] && source ~/.config/spark/hook.zsh   # spark: the AI at the prompt"}


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
    """("hook" | "missing", path): the rc file sources the hook (the
    marker line) or lacks it (path None for a shell without an rc file
    to hook)."""
    path = rc_file(shell)
    if not path:
        return ("missing", None)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            if RC_MARKER in f.read():
                return ("hook", path)
    except OSError:
        pass
    return ("missing", path)


def main(sub, args):
    if sub == "headless":
        return cmd_headless(args)
    if sub == "client":
        return cmd_client(args)
    return cmd_font(args) if sub == "font" else cmd_quiet(args)
