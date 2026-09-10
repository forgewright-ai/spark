# spark.shell -- the gated workstation layer: `spark shell on|off`
# (SITE_SHELL, default off), the tools and the look for a machine that is
# only an AI box, and the hand-back -- rc files and rendered configs
# return from .bak, micro keeps its own settings. shell_off() is the gate
# every shell-layer verb answers with while the layer is off.

import json
import os
import shutil

from . import CONFIG_DIR, HOME, IS_MAC, MARK, config, say
from .site import RC_FILES, RC_MARKER, _spark_link, apply, restore_rc, set_keys


def shell_off(sub):
    """The guard of a shell-layer verb (bar, and quiet's login/boot set
    forms): when the layer is off, say so in the signing shape and
    return 2; else None."""
    if config.load().shell:
        return None
    say("%s %s -- the shell layer is off (spark shell on)" % (MARK, sub))
    return 2


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
SHELL_APPLY_ROWS = ["identity", "dir", "packages", "starship", "pinned",
                    "configs", "rc", "theme", "vt-palette", "terminfo", "quiet-login", "quiet-boot"]
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
                apply(["vt-palette"], stream=True)     # the boot unit: the files exist only now
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
    # console-colors becomes the VGA sixteen, sent to the running console now
    # (then a redraw) and set as the kernel's defaults by the unit at boot.
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
    rc = apply(["configs", "rc", "vt-palette"])       # the boot palette back to VGA too
    from . import packages
    say("packages stay installed -- %s removes them if you want" % (packages.manager() or "the package manager"))
    if rc == 0:
        # the same line `on` prints: this shell still has spark's prompt
        # loaded, and only a new one reads the rc file that was put back
        say("open a new shell (exec $SHELL) -- this one still runs spark's prompt")
    return rc
