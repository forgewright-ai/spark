# spark.site -- the commands that change a site.env choice and apply it:
# `spark shell`, `spark font`, `spark quiet`, `spark model`,
# `spark ember`, `spark headless` (and `spark theme`, in theme.py). Each
# writes the key, then runs bootstrap.sh so the machine follows; editing
# site.env by hand and running bootstrap does the same thing.

import json
import math
import os
import pwd
import re
import shutil
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from . import (CONFIG_DIR, HOME, IS_MAC, MARK, REPO, SITE_ENV, config, confirm, glyph,
               is_wsl, mem_total_gb, paged, say, wait_ready)

# WSL 2: Linux, minus what the VT console and GRUB own (contract 8 lines)
WSL_NO_FONT = "no console on WSL 2: the font lives in Windows Terminal's settings"
WSL_NO_BOOT = "no GRUB on WSL 2: Windows boots it"
WSL_NO_BRAIN = "WSL 2 stops with its last window: not a brain (a Linux box is)"


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


def _downloads_pending(cfg):
    """The chosen roles' model files not on disk yet: models.env rows."""
    from . import engine
    pair = engine.chosen_rows(cfg)
    out = []
    for role in engine.ROLES:
        r = pair.get(role)
        if r and not os.path.isfile(os.path.join(cfg.models_dir, r[1])):
            out.append(r)
    return out


def _announce_downloads(pend):
    """One row per pending download, before bootstrap runs: what, how big."""
    for r in pend:
        say("ok     download     %s (%.1f GB)%s" % (
            r[1], r[3] / 2**30,
            " -- curl's progress bar follows" if sys.stdout.isatty() else ""))


def shell_off(sub):
    """The guard of a shell-layer verb (bar, and quiet's login/boot set
    forms): when the layer is off, say so in the signing shape and
    return 2; else None."""
    if config.load().shell:
        return None
    say("%s %s -- the shell layer is off (spark shell on)" % (MARK, sub))
    return 2


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
    if not IS_MAC and is_wsl():
        # show forms answer; set forms refuse: nothing is written for a
        # console that does not exist
        say("%s font -- %s" % (MARK, WSL_NO_FONT))
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
                MARK, start, _quiet_state(cfg, "login"), "n/a (%s)" % WSL_NO_BOOT if is_wsl() else _quiet_state(cfg, "boot"), audio))
        return 0
    sub = args[0]
    if sub not in QUIET_KEYS or len(args) > 2 or (len(args) == 2 and args[1] not in ("on", "off")):
        say(QUIET_USAGE.rstrip())
        return 2
    linux_only = sub in ("login", "boot")                  # start and audio are both OSes, core
    no_boot = sub == "boot" and not IS_MAC and is_wsl()    # login (motd) is real on WSL; GRUB is not
    if len(args) == 1:                                     # show one state
        if linux_only and IS_MAC:
            say("%s quiet %s -- %s" % (MARK, sub, MAC_NO_QUIET))
            return 0
        if no_boot:
            say("%s quiet %s -- %s" % (MARK, sub, WSL_NO_BOOT))
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
        say("%s quiet %s -- %s" % (MARK, sub, WSL_NO_BOOT))
        return 2
    if linux_only and shell_off("quiet"):
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
        return cmd_model(["auto"])
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
            say("the server that ran here keeps running: spark stop ends it")
    return rc


def _login_hint(url):
    host = urlsplit(url).hostname or url
    return "spark user add NAME on %s (the token shows once), then spark user login NAME here" % host


# ------------------------------------------------------------------ model
MODEL_USAGE = """%s model -- which model this machine serves

  spark model                   the table: size, RAM, license, tested,
                                downloaded, serving, tok/s; the spark pick
                                marked *, the ember +, your own rows u
  spark model NAME              choose it: site.env, download, server restart
                                (a row not under Apache-2.0 or MIT prints
                                its license and asks first)
  spark model auto | none       auto: the largest tested open-license row
                                that fits (smallest beside an ember);
                                none: no model here
  spark model budget [N]        percent of RAM+GPU auto may use (10-95)
  spark model rm NAME           delete a downloaded file that is not in use
  spark model add URL           add your own: --sha256 HEX (non-HF URLs need
                                it), --license "NAME URL" (required); writes
                                ~/.config/spark/models.env, downloads it
  spark model verify            sha256 every downloaded file now; exit 1 on
                                a mismatch (spark check's models row is the
                                cached, daily version of this)

  On a client (spark client URL) the table is the peer's and every choice
  is refused: choose there, or spark client off to serve here again.
""" % MARK


def _client_no(cfg, what):
    """The one line a client answers to a model choice: nothing is served
    here, so a budget, a model or an ember chosen here would silently
    make this machine a server (that is spark client off, by name)."""
    say("%s %s -- a client of %s serves nothing; choose on the peer, or spark client off to serve here again"
        % (MARK, what, cfg.peer_ai_url))
    return 2


def peer_models(cfg):
    """The peer's own model table: GET /api/models on the FORGE, with the
    login token (any role). None when the peer is down, a bare
    llama-server, or a FORGE older than this route."""
    from . import wire
    try:
        req = Request(cfg.peer_ai_url.rstrip("/") + "/api/models", headers=wire._headers(cfg, forge=True))
        with urlopen(req, timeout=wire.HEALTH_TIMEOUT) as r:
            d = json.load(r)
        return d if isinstance(d, dict) and isinstance(d.get("models"), list) else None
    except (HTTPError, URLError, OSError, ValueError):
        return None


def _restart_server(cfg):
    from . import engine, wire
    st = engine.service_state(cfg)
    if st == "loaded":
        if IS_MAC and engine.service_domain(cfg) == "system":
            say(engine.daemon_note(cfg))
            return
        say("ok     server       restarting -- the model loads again (about 30 s) ...")
        engine.service_stop(noreload=False)
        engine.wait_gone(engine.server_pids(cfg.port), 30)
        engine.kickstart(cfg)
        url = wire.serve_url() or cfg.loopback_url()
        if wait_ready("", lambda: wire.health(url) == "ok", 180, 2):
            say("ok     server       ready")
        else:
            say("todo   server       not ready yet -- spark check --watch 5 follows it")
        from . import check
        check.refresh()
    elif engine.pidfile_pid():
        from . import serve
        serve.cmd_stop([])
        serve.cmd_serve([])
    else:
        say("ok     server       not running -- the next spark serve uses it")


SOURCE_MARKS = {"repo": " ", "user": "u"}


def model_rows(cfg, serving=None):
    """The model table as data: [{name, gb, ram_gb, fits, downloaded,
    chosen, role, serving, speed, speed_kind, source, mark, tested,
    license, open, note}] in model_tables() order (the list, then yours).
    `role` is "spark", "ember" or "" from engine.chosen_rows. `source` is
    "repo" or "user"; `mark` is the second column's glyph (SOURCE_MARKS:
    blank, `u` yours); `tested` says the row was proven on the line and
    `open` that its license is one auto may take (config.is_open).
    `serving` is the model name a brain answers with; None
    asks the brain (the FORGE passes its own). `speed` is tok/s and
    `speed_kind` "measured" or "estimate" (engine.speed_of)."""
    from . import engine, wire
    # a client serves nothing: its own RAM is no budget, so `fits` is None
    budget = None if cfg.client else mem_total_gb() * cfg.ai_budget / 100.0
    pair = engine.chosen_rows(cfg)
    chosen = pair["spark"][1] if pair.get("spark") else ""
    role_of = {}
    for role in engine.ROLES:
        r = pair.get(role)
        if r and r[1] not in role_of:
            role_of[r[1]] = role
    if serving is None:
        serving = ""
        try:
            serving = wire.resolve_brain(cfg).model
        except wire.BrainError:
            pass
    out = []
    for row in config.model_tables():
        name, fname, _url, nbytes, _sha, ram, source, tested, license_, note = row
        speed, kind = engine.speed_of(cfg, row)
        out.append({"name": name, "gb": round(nbytes / 2**30, 1), "ram_gb": ram, "fits": (ram <= budget) if budget is not None else None,
                    "downloaded": os.path.isfile(os.path.join(cfg.models_dir, fname)),
                    "chosen": fname == chosen, "role": role_of.get(fname, ""),
                    "serving": bool(serving) and fname.replace(".gguf", "") == serving,
                    "speed": speed, "speed_kind": kind, "source": source,
                    "mark": SOURCE_MARKS.get(source, " "), "tested": tested,
                    "license": license_, "open": config.is_open(license_), "note": note})
    return out


def model_line(r, marks=None, width=13):
    """One table row: the pick mark (spark *, ember +), the source mark
    (blank the list, `u` yours), the name, the file size, the RAM verdict,
    the license's first word (`open` marks one auto may take), `line` when
    the row was proven on the line, downloaded / serving, and the speed --
    `~N tok/s` an estimate, `N tok/s` measured; nothing for a row that
    does not fit. `width` pads the name column (the caller widens it past
    13 for a longer name). Every row stays within 80 columns."""
    marks = marks or {"spark": "*", "ember": "+"}
    state = "serving" if r["serving"] else ("downloaded" if r["downloaded"] else "")
    if r["fits"] is None:
        speed = ""                       # a client: the peer's business
    else:
        speed = ("%s%d tok/s" % ("~" if r["speed_kind"] == "estimate" else "", r["speed"])) if r["fits"] else "too big"
    lic = ((r["license"] or "").split() or [""])[0][:10]
    # padded columns, right-aligned numbers: the eye reads a table, not a
    # sentence; 57 + width columns, so a 23-char name still fits 80
    return ("  %s%s %-*s %5.1f GB %2.0f GB %-10s %-4s %-10s %9s"
            % (marks.get(r["role"], " "), r["mark"], width, r["name"], r["gb"], r["ram_gb"],
               lic, "line" if r["tested"] else "", state, speed)).rstrip()


def print_model_table(cfg):
    """The one table `spark model list` and `spark ember list` share:
    every row of models.env and yours with its RAM verdict, the spark pick
    marked * and the ember pick + (the marks bootstrap.sh --list-models
    draws), a second mark `u` for your own rows, the license's first word,
    `line` on a row proven on the line (auto reads only those, under an
    open license), and a last column with the generation speed: `~N
    tok/s` an estimate for this backend, `N tok/s` measured here (spark
    bench, or a real turn); nothing for a row that does not fit. A row's
    note follows it, indented. Every row stays within 80 columns."""
    from . import engine
    if cfg.client:
        # a client: never this machine's RAM. The peer's table when its
        # FORGE answers /api/models (the box's RAM, budget, picks,
        # speeds); else the rows alone, no verdict
        peer = peer_models(cfg)
        if peer:
            say("%s model%sa client of %s -- the peer's table: %.0f GB for models, budget %.0f GB (%d%%), %s" % (
                MARK, glyph("sep"), cfg.peer_ai_url, peer.get("total_gb", 0), peer.get("budget_gb", 0),
                peer.get("budget_pct", 0), peer.get("backend", "?")))
            if peer.get("cap_note"):
                say("  " + peer["cap_note"])
            rows = peer["models"]
        else:
            say("%s model%sa client of %s -- nothing is served here; what fits is the peer's business (spark model there)" % (
                MARK, glyph("sep"), cfg.peer_ai_url))
            rows = model_rows(cfg)
    else:
        budget = mem_total_gb() * cfg.ai_budget / 100.0
        say("%s model%sSITE_AI_MODEL=%s SITE_EMBER_MODEL=%s%s%.0f GB for models (RAM + GPU), budget %.0f GB (%d%%), %s" % (
            MARK, glyph("sep"), cfg.model_choice, cfg.ember_model, glyph("sep"), mem_total_gb(), budget, cfg.ai_budget, engine.backend(cfg)))
        note = engine.cap_note(cfg)
        if note:
            say("  " + note)
        rows = model_rows(cfg)
    width = max([13] + [len(r["name"]) for r in rows])
    say("     %-*s %8s %5s %-10s %-4s %-10s %9s" % (width, "model", "file", "RAM", "license", "line", "", "fits"))
    for r in rows:
        say(model_line(r, width=width))
        if r["note"]:
            say("      " + r["note"])
    known = {row[1] for row in config.model_tables()}
    others = [f for f in os.listdir(cfg.models_dir) if f.endswith(".gguf") and f not in known] if os.path.isdir(cfg.models_dir) else []
    for f in others:
        say("    %-13s %5.1f GB file   (not in models.env; SPARK_MODEL=%s serves it)" % (
            "-", os.path.getsize(os.path.join(cfg.models_dir, f)) / 2**30, f))
    say("  * = spark (the prompt line), + = ember (conversations), u = yours")
    say("  auto picks among the rows tested on the line (line) under %s" % " or ".join(config.OPEN_LICENSES))
    return 0


def _license_ok(row, verb):
    """A row under a license auto would not take (config.is_open: not
    Apache-2.0 or MIT) prints its license line -- and its note, when
    there is one -- and gets a yes before the download: SPARK_YES=1 in
    the environment, or stdin not a tty (a script, a pipe), counts as yes
    without asking. An open-license row downloads without a question."""
    name, license_, note = row[0], row[8], row[9]
    if config.is_open(license_):
        return True
    say("%s license: %s" % (name, license_ or "none on file"))
    if note:
        say("  " + note)
    if os.environ.get("SPARK_YES") == "1" or not sys.stdin.isatty():
        return True
    if not confirm("download it"):
        say("spark %s: cancelled" % verb)
        return False
    return True


# ------------------------------------------------------------------ add
QUANT_RE = re.compile(r"-(q4-k-m|q5-k-m|q8-0|f16|bf16|iq[0-9][a-z0-9-]*)$")
USER_MODELS_FILE = os.path.join(CONFIG_DIR, "models.env")


def _short(path):
    return "~" + path[len(HOME):] if path.startswith(HOME + "/") else path


def _source_file(source):
    return USER_MODELS_FILE if source == "user" else os.path.join(REPO, "models.env")


def _model_name(fname):
    """The file stem, lowercased, dots and underscores to dashes, a
    trailing quantization token stripped: Qwen_Qwen3-4B-Q4_K_M.gguf ->
    qwen-qwen3-4b."""
    stem = os.path.splitext(fname)[0].lower().replace(".", "-").replace("_", "-")
    return QUANT_RE.sub("", stem)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _head(url, extra_headers=None, follow=True):
    """(headers, error) -- a HEAD request through urllib; redirects
    followed and the final response's headers returned, or, with
    follow=False, the FIRST response's headers even when it is a 3xx
    (huggingface.co puts the file's size and sha256 on its redirect, and
    the CDN it points at knows neither). error is a one-line reason, or
    None."""
    req = Request(url, method="HEAD", headers=dict(extra_headers or {}, **{"User-Agent": "spark"}))
    opener = urlopen if follow else build_opener(_NoRedirect()).open
    try:
        with opener(req, timeout=20) as resp:
            return resp.headers, None
    except HTTPError as e:
        if not follow and 300 <= e.code < 400:
            return e.headers, None
        return None, "could not reach %s -- %s" % (url, e)
    except (URLError, OSError) as e:
        return None, "could not reach %s -- %s" % (url, e)


def _probe_model_url(url, sha):
    """(bytes, sha256, error) for `spark model add URL`: huggingface.co is
    auto-verified from its LFS headers (x-linked-size, x-linked-etag, on
    the redirect it answers with); any other host needs --sha256 and its
    size from a plain HEAD."""
    host = urlsplit(url).hostname or ""
    if host == "huggingface.co":
        hurl = url + ("&download=true" if "?" in url else "?download=true")
        headers, err = _head(hurl, follow=False)
        if err:
            return None, None, err
        size = headers.get("x-linked-size")
        etag = (headers.get("x-linked-etag") or "").strip('"').lower()
        if not size or not re.match(r"^[0-9a-f]{64}$", etag):
            return None, None, "not an LFS file -- add --sha256 HEX"
        return int(size), etag, None
    if not sha:
        return None, None, "%s is not huggingface.co -- add --sha256 HEX" % host
    if not re.match(r"^[0-9a-fA-F]{64}$", sha):
        return None, None, "--sha256 needs 64 hex characters"
    headers, err = _head(url)
    if err:
        return None, None, err
    size = headers.get("Content-Length")
    if not size:
        return None, None, "%s answered no Content-Length" % url
    return int(size), sha.lower(), None


def _model_add(args):
    url = sha = license_ = None
    it = iter(args)
    for a in it:
        if a == "--sha256":
            sha = next(it, None)
        elif a == "--license":
            license_ = next(it, None)
        elif url is None:
            url = a
        else:
            say(MODEL_USAGE.rstrip())
            return 2
    if not url:
        say(MODEL_USAGE.rstrip())
        return 2
    if not license_:
        say('spark model add: --license "NAME URL" is required -- your own row states its license too')
        return 2
    nbytes, sha256, err = _probe_model_url(url, sha)
    if err:
        say("spark model add: %s" % err)
        return 2
    fname = os.path.basename(urlsplit(url).path)
    if not fname:
        say("spark model add: %s has no file name" % url)
        return 2
    name = _model_name(fname)
    if not name:
        say("spark model add: %s has no name once the quantization is stripped" % fname)
        return 2
    existing = {r[0]: r[6] for r in config.model_tables()}
    if name in existing:
        say("spark model add: %s is already in %s" % (name, _short(_source_file(existing[name]))))
        return 2
    ram_gb = math.ceil(nbytes / 2**30 * 1.1 + 1.5)
    stem = name.upper().replace("-", "_")
    set_keys(_file=USER_MODELS_FILE, _quiet=True, **{
        "MODEL_" + stem: '"%s %s %d %s %d"' % (fname, url, nbytes, sha256, ram_gb),
        "MODEL_" + stem + "_LICENSE": '"%s"' % license_})
    say("ok     model        added %s (%.1f GB, ram %d GB) -- %s" % (
        name, nbytes / 2**30, ram_gb, _short(USER_MODELS_FILE)))
    return cmd_model([name])


def cmd_model(args):
    from . import engine
    cfg = config.load()
    if args and args[0] in ("-h", "--help", "help"):
        say(MODEL_USAGE.rstrip())
        return 0
    if args[0:1] == ["add"]:
        return _model_add(args[1:])
    if args[0:1] == ["verify"]:
        from . import verify
        rows = verify.verify_all(cfg, force=True)
        if not rows:
            say("spark model verify: no downloaded model")
            return 0
        bad = False
        width = max(12, max(len(r["name"]) for r in rows))
        for r in rows:
            if r["status"] == "ok":
                say("%-7s%-*s sha256 ok (%.1f GB)" % ("ok", width, r["name"], r["bytes"] / 2**30))
            else:
                bad = True
                say("%-7s%-*s sha256 MISMATCH -- spark model rm %s; spark model %s" % (
                    "bad", width, r["name"], r["name"], r["name"]))
        return 1 if bad else 0
    rows = config.model_tables()
    if not args or args[0] in ("list", "status"):
        return paged(lambda: print_model_table(cfg))
    if args[0] == "budget":
        if len(args) == 1:
            if cfg.client:
                return print_model_table(cfg)
            gb = mem_total_gb() * cfg.ai_budget / 100.0
            say("%s model budget%s%d%% of %.0f GB = %.0f GB" % (MARK, glyph("sep"), cfg.ai_budget, mem_total_gb(), gb))
            return print_model_table(cfg)
        if len(args) != 2 or not args[1].isdigit() or not 10 <= int(args[1]) <= 95:
            say(MODEL_USAGE.rstrip())
            return 2
        if cfg.client:
            return _client_no(cfg, "model budget")
        set_keys(SITE_AI_BUDGET=args[1])
        pend = [] if os.environ.get("SPARK_NO_APPLY") else _downloads_pending(config.load())
        _announce_downloads(pend)
        rc = apply(["model", "ember"], stream=bool(pend))
        if rc != 0:
            return rc
        if not os.environ.get("SPARK_NO_APPLY"):
            cfg = config.load()
            if engine.model_file(cfg):
                _restart_server(cfg)
            else:
                say("ok     server       nothing to serve -- left as it is")
        return print_model_table(config.load())
    if args[0] == "rm":
        if len(args) != 2:
            say(MODEL_USAGE.rstrip())
            return 2
        if cfg.client:
            return _client_no(cfg, "model rm")
        match = [r for r in rows if r[0] == args[1]]
        fname = match[0][1] if match else args[1]
        path = os.path.join(cfg.models_dir, fname)
        if not os.path.isfile(path):
            say("spark model: %s is not downloaded -- nothing to remove" % fname)
            return 2
        if fname == engine.chosen_model_name(cfg) or path == engine.model_file(cfg):
            say("spark model: %s is in use -- choose another first" % fname)
            return 1
        os.remove(path)
        say("ok     removed      %s" % path)
        return 0
    name = args[0]
    match = [r for r in rows if r[0] == name]
    if name not in ("auto", "none") and not match:
        say("spark model: no model named %s -- one of: auto none %s" % (name, " ".join(r[0] for r in rows)))
        return 2
    if cfg.client:
        return _client_no(cfg, "model")
    if match and not _license_ok(match[0], "model"):
        return 1
    set_keys(SITE_AI_MODEL=name)
    pend = [] if os.environ.get("SPARK_NO_APPLY") else _downloads_pending(config.load())
    _announce_downloads(pend)
    rc = apply(["model"], stream=bool(pend))
    if rc != 0:
        return rc
    if os.environ.get("SPARK_NO_APPLY"):
        return 0
    cfg = config.load()
    if name == "none" or not engine.model_file(cfg):
        say("ok     server       nothing to serve -- left as it is")
        return 0
    _restart_server(cfg)
    return 0


# ------------------------------------------------------------------ ember
EMBER_USAGE = """%s ember -- the conversational model

  spark ember                   the two roles: model, file, loaded or not
  spark ember NAME              choose it: site.env, download, server restart
  spark ember auto              the largest that fits beside the spark model
  spark ember none              no second model -- spark answers everything
  spark ember list              the model table, the spark pick marked *,
                                the ember + (the same table as spark model)
""" % MARK


def cmd_ember(args):
    from . import engine, wire
    cfg = config.load()
    if args and args[0] in ("-h", "--help", "help"):
        say(EMBER_USAGE.rstrip())
        return 0
    if args and args[0] == "list":
        return paged(lambda: print_model_table(cfg))
    if not args or args[0] == "status":
        pair = engine.chosen_rows(cfg)
        files = engine.roles(cfg)
        url = wire.serve_url()
        status = engine.models_status(cfg, url) if url and wire.health(url) == "ok" else {}
        say("%s ember%sSITE_EMBER_MODEL=%s" % (MARK, glyph("sep"), cfg.ember_model))
        for role in engine.ROLES:
            f, r = files[role], pair.get(role)
            if not f and not r:
                say("  %-5s  none -- %s" % (role, "spark answers everything (spark ember NAME adds one)"
                                            if role == "ember" else "no model (./bootstrap.sh downloads one)"))
            elif f:
                say(("  %-5s  %-14s %5.1f GB  %s" % (role, engine.model_stem(f),
                                                     os.path.getsize(f) / 2**30, status.get(role, ""))).rstrip())
            else:
                say("  %-5s  %-14s not downloaded (./bootstrap.sh)" % (role, r[1].replace(".gguf", "")))
        return 0
    name = args[0]
    rows = config.model_tables()
    match = [r for r in rows if r[0] == name]
    if name not in ("auto", "none") and not match:
        say("spark ember: no model named %s -- one of: auto none %s   (spark ember list)" % (name, " ".join(r[0] for r in rows)))
        return 2
    if cfg.client:
        return _client_no(cfg, "ember")
    if match and not _license_ok(match[0], "ember"):
        return 1
    set_keys(SITE_EMBER_MODEL=name)
    pend = [] if os.environ.get("SPARK_NO_APPLY") else _downloads_pending(config.load())
    _announce_downloads(pend)
    rc = apply(["model", "ember"], stream=bool(pend))
    if rc != 0:
        return rc
    if os.environ.get("SPARK_NO_APPLY"):
        return 0
    cfg = config.load()
    if not engine.model_file(cfg):
        say("ok     server       nothing to serve -- left as it is")
        return 0
    _restart_server(cfg)
    return 0


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


# The shell layer's rendered look: what install.sh renders only with
# SITE_SHELL=on and what `spark shell off` therefore hands back. The
# user-owned runtime palette (~/.config/spark/theme.env, console-colors)
# is core -- `spark theme` owns it, outside the gate -- and stays. micro's
# settings.json is not here: seeded once, it is micro's (the user's
# options live in it); `off` only drops the colorscheme key it seeded.
RENDERED_FILES = (".tmux.conf", ".config/starship.toml", ".config/btop/btop.conf",
                  ".config/micro/colorschemes/spark.micro")
MICRO_SETTINGS = os.path.join(HOME, ".config", "micro", "settings.json")


def restore_rendered():
    """spark shell off: every shell-layer rendered config goes back the way
    restore_rc hands back the rc files -- <path>.bak moved back when it
    exists, the file removed when there was none (that was the pre-spark
    state), never an empty husk left behind. Only regular files go: a
    symlink in one of these spots is not a render of ours. Returns
    [(path, what)]."""
    done = []
    for rel in RENDERED_FILES:
        path = os.path.join(HOME, rel)
        if os.path.islink(path) or not os.path.isfile(path):
            continue
        os.unlink(path)
        bak = path + ".bak"
        name = os.path.basename(path)
        if os.path.lexists(bak):
            os.rename(bak, path)
            done.append((path, "restored from %s.bak" % name))
        else:
            done.append((path, "removed (no %s.bak: there was no file before)" % name))
    return done


def micro_settings_reset(path=MICRO_SETTINGS):
    """The inverse of theme.micro_colorscheme: the colorscheme key the seed
    put in micro's settings.json goes (the scheme file is gone with the
    layer), every other option stays -- the file is micro's. Returns True
    when the key was dropped; the file is never removed."""
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return False
    if not isinstance(d, dict) or d.get("colorscheme") != "spark":
        return False
    del d["colorscheme"]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=4)
        f.write("\n")
    return True


# ------------------------------------------------------------------ shell
SHELL_USAGE = """%s shell -- spark's own shell: tmux, starship, fzf, eza, bat, btop

  spark shell                   the state: off (the prompt widget only) or on
  spark shell on                SITE_SHELL=on: the tools, the Nerd Font, the
                                console; the rc files become spark's (yours
                                move to .bak); with a theme set, tmux and
                                the console wear the same palette (a micro
                                you have too)
  spark shell off               SITE_SHELL=off: the rc files and the rendered
                                look (tmux, starship, btop, micro's scheme)
                                come back from .bak, or go; packages stay
""" % MARK
# the bootstrap rows the switch flips (bootstrap.sh gates them on
# SITE_SHELL); the row names are bootstrap.sh's, not check.py's. The
# console-font and hostname rows are core, so they are not filtered for here.
SHELL_APPLY_ROWS = ["identity", "dir", "apt", "brew", "starship", "pinned",
                    "configs", "rc", "theme", "terminfo", "quiet-login", "quiet-boot"]
SHELL_TOOLS = "tmux, starship, fzf, zoxide, eza, bat, btop"


def rc_state(path):
    """"spark's" (the repo's symlink), "hook" (the marked line), "yours"
    (anything else), or "absent" -- for one rc file of RC_FILES."""
    if _spark_link(path):
        return "spark's"
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return "hook" if RC_MARKER in f.read() else "yours"
    except OSError:
        return "absent"


def cmd_shell(args):
    cfg = config.load()
    if args and args[0] in ("-h", "--help", "help"):
        say(SHELL_USAGE.rstrip())
        return 0
    if not args or args[0] == "status":
        if not cfg.shell:
            say("%s shell -- SITE_SHELL=off -- the prompt widget only" % MARK)
            say("  spark shell on adds %s," % SHELL_TOOLS)
            say("  the Nerd Font, and makes the rc files spark's")
            return 0
        say("%s shell -- SITE_SHELL=on -- the shell layer is spark's" % MARK)
        say("  rc files: " + ", ".join("~/%s (%s)" % (n, rc_state(os.path.join(HOME, n))) for n in RC_FILES))
        say("  " + ", ".join("%s %s" % (t, "yes" if shutil.which(t) else "no") for t in ("starship", "tmux")))
        return 0
    if args[0] not in ("on", "off"):
        say(SHELL_USAGE.rstrip())
        return 2
    if args[0] == "on":
        set_keys(SITE_SHELL="on")
        rc = apply(SHELL_APPLY_ROWS, stream=True)
        if rc == 0:
            # the palette lands here, not at setup: turning the layer on is
            # where a user asks for spark's look. bootstrap's theme row wrote
            # theme.env; console-colors and the macOS profile are ours.
            cfg = config.load()
            if cfg.theme != "none" and not os.environ.get("SPARK_NO_APPLY"):
                from . import theme
                theme.write_runtime(cfg.theme)
                theme.apply_console()
                say("ok     theme        %s -> ~/.config/spark/theme.env (+ console-colors)" % cfg.theme)
                if IS_MAC:
                    theme.profile(cfg, False)
            say("open a new shell (exec $SHELL)")
        return rc
    set_keys(SITE_SHELL="off")
    for path, what in restore_rc() + restore_rendered():
        say("ok     restore      ~%s -- %s" % (path[len(HOME):], what))
    if micro_settings_reset():
        say("ok     restore      ~/.config/micro/settings.json -- colorscheme key dropped, the rest is micro's")
    # the palette came with the layer, so it goes with it. SITE_THEME stays
    # in site.env (spark shell on paints it again); theme.env goes and
    # console-colors becomes the VT reset the hook cats at the next login --
    # and the running console gets that reset now, since no shell restart
    # can undo a palette the terminal itself is holding.
    if any(os.path.exists(os.path.join(CONFIG_DIR, f)) for f in ("theme.env", "console-colors")):
        from . import theme
        theme.write_runtime("none")     # config, so SPARK_NO_APPLY does it too
        theme.apply_console()           # the running VT, not just the next login
        say("ok     theme        the console palette is back to its own"
            + ("; Terminal.app keeps the spark profile until you change it there" if IS_MAC else ""))
    if not os.environ.get("SPARK_NO_APPLY"):
        from . import run
        trc, _ = run(["tmux", "list-sessions"])
        if trc == 0:
            if os.path.isfile(os.path.join(HOME, ".tmux.conf")):
                run(["tmux", "source-file", os.path.join(HOME, ".tmux.conf")])
                say("ok     tmux         reloaded (your .tmux.conf)")
            else:
                say("ok     tmux         running sessions keep the look until tmux restarts")
    rc = apply(["configs", "rc"])
    say("packages stay installed -- apt or brew removes them if you want")
    if rc == 0:
        # the same line `on` prints: this shell still has spark's prompt
        # loaded, and only a new one reads the rc file that was put back
        say("open a new shell (exec $SHELL)")
    return rc


def main(sub, args):
    if sub == "shell":
        return cmd_shell(args)
    if sub == "model":
        return cmd_model(args)
    if sub == "ember":
        return cmd_ember(args)
    if sub == "headless":
        return cmd_headless(args)
    if sub == "client":
        return cmd_client(args)
    return cmd_font(args) if sub == "font" else cmd_quiet(args)
