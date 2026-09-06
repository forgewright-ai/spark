# spark.theme -- the chosen palette, and the one place it cannot be
# symlinked into: Terminal.app on macOS, whose profiles are archived NSColor
# objects inside a plist. `spark theme profile` writes and imports one from
# the palette; on Linux the emulator is the user's, so it prints the palette
# for them to apply.

import os
import plistlib
import subprocess
import time

from . import CONFIG_DIR, HOME, IS_MAC, MARK, REPO, config, glyph, run, say



def palette(cfg):
    """dict THEME_* for the site's theme, or None for `none`"""
    return config.theme_palette(cfg.theme, REPO)


def _hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def _archive(objects, top_index=1):
    """A minimal NSKeyedArchiver binary plist: $objects[0] is $null."""
    return plistlib.dumps({"$version": 100000, "$archiver": "NSKeyedArchiver",
                           "$top": {"root": plistlib.UID(top_index)},
                           "$objects": ["$null"] + objects}, fmt=plistlib.FMT_BINARY)


def ns_color(hexstr):
    r, g, b = _hex_rgb(hexstr)
    return _archive([
        {"$class": plistlib.UID(2), "NSColorSpace": 1,
         "NSRGB": ("%.6f %.6f %.6f" % (r, g, b)).encode() + b"\x00"},
        {"$classname": "NSColor", "$classes": ["NSColor", "NSObject"]},
    ])


def ns_font(name, size):
    return _archive([
        {"$class": plistlib.UID(3), "NSName": plistlib.UID(2), "NSSize": size, "NSfFlags": 16},
        name,
        {"$classname": "NSFont", "$classes": ["NSFont", "NSObject"]},
    ])


def profile_dict(name, pal, font_name="JetBrainsMonoNFM-Regular", font_size=13.0):
    keys = ["Black", "Red", "Green", "Yellow", "Blue", "Magenta", "Cyan", "White",
            "BrightBlack", "BrightRed", "BrightGreen", "BrightYellow", "BrightBlue",
            "BrightMagenta", "BrightCyan", "BrightWhite"]
    d = {"name": name, "type": "Window Settings", "ProfileCurrentVersion": 2.07,
         "BackgroundColor": ns_color(pal["THEME_BG"]),
         "TextColor": ns_color(pal["THEME_FG"]),
         "TextBoldColor": ns_color(pal["THEME_FG"]),
         "CursorColor": ns_color(pal["THEME_ACCENT"]),
         "SelectionColor": ns_color(pal["THEME_ANSI_0"]),
         "Font": ns_font(font_name, float(font_size)),
         "columnCount": 120, "rowCount": 36, "useOptionAsMetaKey": True,
         "keyMapBoundKeys": KEY_MAP}
    for i, k in enumerate(keys):
        d["ANSI%sColor" % k] = ns_color(pal["THEME_ANSI_%d" % i])
    return d


# Terminal.app sends nothing for Shift+Up/Down (Shift+Left/Right it does),
# so micro cannot select by line there; nor for Ctrl+arrows. The profile
# binds the xterm sequences micro's terminfo already knows. Keys: $ Shift,
# ^ Control; F700..F703 = Up, Down, Left, Right. Values hold the real ESC
# byte, the way Apple's own keyMappings.plist stores "$F702" (Shift+Left,
# one of the two it does map) -- the text "\\033" would be typed as text.
ESC = "\x1b"
KEY_MAP = {
    "$F700": ESC + "[1;2A", "$F701": ESC + "[1;2B", "$F702": ESC + "[1;2D", "$F703": ESC + "[1;2C",
    "^F700": ESC + "[1;5A", "^F701": ESC + "[1;5B", "^F702": ESC + "[1;5D", "^F703": ESC + "[1;5C",
}


def read_back(path):
    """Decode a .terminal file's colours: proof the archive is readable."""
    with open(path, "rb") as f:
        d = plistlib.load(f)
    out = {}
    for k, v in d.items():
        if isinstance(v, bytes):
            a = plistlib.loads(v)
            obj = a["$objects"][1]
            if "NSRGB" in obj:
                out[k] = obj["NSRGB"].rstrip(b"\x00").decode()
            elif "NSName" in obj:
                out[k] = "%s %s" % (a["$objects"][obj["NSName"].data], obj["NSSize"])
    return out


def table(cfg):
    notes = {"none": "the terminal's own colours", "gruvbox-dark": "preferred: it matches the logo"}
    say("%s theme%sSITE_THEME=%s" % (MARK, glyph("sep"), cfg.theme))
    for p in ["none"] + palettes():
        note = notes.get(p, "yours: ~/.config/spark/themes/%s.env" % p if yours(p) else "")
        say("  %-18s %-34s %s" % (p, note, "current" if p == cfg.theme else ""))
    return 0


def show(cfg):
    pal = palette(cfg)
    say("%s theme show%s%s" % (MARK, glyph("sep"), cfg.theme))
    if not pal:
        say("  SITE_THEME=none: the terminal keeps its own colours -- tmux and starship use named ones")
        return 0
    for k in ("THEME_BG", "THEME_FG", "THEME_ACCENT", "THEME_MUTED"):
        say("  %-13s %s" % (k[6:].lower(), pal[k]))
    say("  ansi          " + " ".join(pal["THEME_ANSI_%d" % i] for i in range(8)))
    say("  bright        " + " ".join(pal["THEME_ANSI_%d" % i] for i in range(8, 16)))
    say("  written to    %s (by bootstrap.sh or spark theme NAME)" % os.path.join(CONFIG_DIR, "theme.env"))
    say("  console       %s (TERM=linux only: the rc hook applies it)" % os.path.join(CONFIG_DIR, "console-colors"))
    return 0


def profile(cfg, dry):
    pal = palette(cfg)
    if not pal:
        say("skip   profile      SITE_THEME=none: no spark profile to carry the font -- spark theme NAME makes one")
        return 0
    if not IS_MAC:
        say("skip   profile      not macOS: apply %s in your terminal emulator's settings" % os.path.join(CONFIG_DIR, "theme.env"))
        return 0
    name = "spark-" + cfg.theme
    path = os.path.join(CONFIG_DIR, name + ".terminal")
    # binary: an XML plist cannot hold the ESC byte the key map needs
    want = plistlib.dumps(profile_dict(name, pal, cfg.font_face, cfg.font_size), fmt=plistlib.FMT_BINARY)
    have = b""
    try:
        with open(path, "rb") as f:
            have = f.read()
    except OSError:
        pass
    rc, out = run(["defaults", "read", "com.apple.Terminal", "Default Window Settings"])
    is_default = rc == 0 and out.strip() == name
    rc, out = run(["defaults", "read", "com.apple.Terminal", "Window Settings"], timeout=10)
    imported = rc == 0 and ('"%s"' % name in out or "%s =" % name in out)
    live_keys = rc == 0 and "keyMapBoundKeys" in out.split('"%s" =' % name, 1)[-1][:4000]
    stale_dup = rc == 0 and ('"%s 1"' % name in out)
    if have == want and imported and is_default and live_keys and not stale_dup:
        say("ok     profile      Terminal.app profile %s is the default%s" % (name, _switch_windows(name, path, cfg.font_face, cfg.font_size)))
        return 0
    if dry:
        say("would  profile      write %s, import it, make it Terminal.app's default" % path)
        return 0
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(path, "wb") as f:
        f.write(want)
    colours = read_back(path)
    if colours.get("BackgroundColor") is None:
        say("skip   profile      wrote %s but could not read it back -- not importing" % path)
        return 1
    if not _install_profile(name, profile_dict(name, pal, cfg.font_face, cfg.font_size), path):
        say("skip   profile      wrote %s but could not write Terminal.app's preferences" % path)
        return 1
    say("ok     profile      %s written, imported and set as default%s" % (name, _switch_windows(name, path, cfg.font_face, cfg.font_size)))
    return 0


def _live_sets():
    """The settings sets the RUNNING Terminal.app knows -- its own list,
    not the preferences file, which it reads only at launch. [] when it is
    not running or refuses the script."""
    rc, out = run(["osascript", "-e", 'tell application "Terminal" to get name of every settings set'], timeout=8)
    return [n.strip() for n in out.split(",")] if rc == 0 else []


def _switch_windows(name, path, face=None, size=None):
    """The running Terminal.app takes the profile now: imported live by
    opening the .terminal file when its list lacks the name (that is the
    one live import there is; it opens a window with the profile, and
    never a duplicate since the name was absent), then made the default
    and set on every tab of every window by script. Returns the row's
    note: switched, or what remains by hand."""
    live = _live_sets()
    if not live:
        return " (new windows use it)"
    if name not in live:
        run(["open", "-g", path], timeout=8)
        time.sleep(1.5)
        if name not in _live_sets():
            return " (new windows use it; quit and reopen Terminal.app for the open ones)"
    # the live copy may predate a font change: the face and size go in by script too
    font = ('set font name of s to "%s"\nset font size of s to %s\n' % (face, int(float(size)))) if face and size else ""
    script = ('tell application "Terminal"\nset s to settings set "%s"\n%sset default settings to s\n'
              'repeat with w in windows\nrepeat with t in tabs of w\nset current settings of t to s\n'
              'end repeat\nend repeat\nend tell') % (name, font)
    rc, _ = run(["osascript", "-e", script], timeout=8)
    return "; open windows switched" if rc == 0 else " (new windows use it; open ones: Terminal > Shell > Show Inspector)"


def _terminal_prefs(path):
    """Terminal.app's preferences as a dict, {} when there are none.
    `defaults export` writes XML that carries the key map's ESC byte raw --
    which no XML parser accepts -- so plutil (lenient) turns it into a
    binary plist first."""
    xml, bin_ = path + ".export", path + ".bin"
    try:
        rc, _ = run(["defaults", "export", "com.apple.Terminal", xml], timeout=10)
        if rc != 0 or not os.path.exists(xml):
            return {}
        rc, _ = run(["plutil", "-convert", "binary1", "-o", bin_, xml], timeout=10)
        if rc != 0:
            return {}
        with open(bin_, "rb") as f:
            prefs = plistlib.load(f)
        return prefs if isinstance(prefs, dict) else {}
    except Exception:
        return {}
    finally:
        for f in (xml, bin_):
            try:
                os.remove(f)
            except OSError:
                pass


def _install_profile(name, d, path):
    """Put the profile into Terminal.app's preferences under its name --
    replacing an older one of that name -- and make it the default. Through
    `defaults export` / `defaults import` (cfprefsd), never `open`: handing
    Terminal.app the .terminal file imports a duplicate ("NAME 1") when the
    name exists, and a duplicate is exactly what a changed profile made.
    Earlier duplicates of that shape are removed on the way."""
    prefs = _terminal_prefs(path)
    ws = prefs.get("Window Settings")
    if not isinstance(ws, dict):
        ws = prefs["Window Settings"] = {}
    ws[name] = d
    for k in list(ws):
        rest = k[len(name):]
        if k.startswith(name) and rest.startswith(" ") and rest.strip().isdigit():
            del ws[k]
    prefs["Default Window Settings"] = name
    prefs["Startup Window Settings"] = name
    tmp = path + ".prefs"
    with open(tmp, "wb") as f:
        plistlib.dump(prefs, f, fmt=plistlib.FMT_BINARY)
    rc, _ = run(["defaults", "import", "com.apple.Terminal", tmp], timeout=10)
    try:
        os.remove(tmp)
    except OSError:
        pass
    return rc == 0


def palettes():
    """Every palette name: the repository's themes/*.env and your own
    ~/.config/spark/themes/*.env (config.theme_names)."""
    return config.theme_names(REPO)


def yours(name):
    """True when the palette's file is in your config dir, not the repo's."""
    path = config.theme_path(name, REPO)
    return bool(path) and path.startswith(os.path.join(CONFIG_DIR, "themes") + os.sep)


def write_runtime(name):
    """The palette's two runtime files under ~/.config/spark, written by
    `spark theme NAME` and `spark setup` only (one writer; bootstrap's
    theme row writes theme.env too when the shell layer is on, and notes
    console-colors when it sees it):
      theme.env       KEY=value, what tmux/starship/btop were rendered from
                      and what the FORGE page reads (removed for `none`)
      console-colors  the Linux VT palette, precomputed: \\033]P<n><rrggbb>
                      per ansi colour 0-15. hook.bash/.zsh cat it only when
                      TERM=linux, so an xterm's scrollback is never touched.
                      For `none` an existing file becomes the one reset
                      escape \\033]R: the console lets the palette go at the
                      next login."""
    theme_env = os.path.join(CONFIG_DIR, "theme.env")
    console = os.path.join(CONFIG_DIR, "console-colors")
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if name == "none":
        try:
            os.remove(theme_env)
        except OSError:
            pass
        if os.path.exists(console):
            with open(console, "w", encoding="utf-8") as f:
                f.write("\033]R\n")
        return
    pal = config.theme_palette(name, REPO)
    order = (["THEME_BG", "THEME_FG", "THEME_ACCENT", "THEME_MUTED", "THEME_BTOP"] + ["THEME_ANSI_%d" % i for i in range(16)]
             + ["THEME_LOGO"])          # optional: present only when the palette names it
    with open(theme_env, "w", encoding="utf-8") as f:       # bootstrap's order, so it agrees
        f.write("".join("%s=%s\n" % (k, pal[k]) for k in order if k in pal))
    esc = "".join("\033]P%x%s" % (i, pal["THEME_ANSI_%d" % i].lstrip("#").lower()) for i in range(16))
    with open(console, "w", encoding="utf-8") as f:
        f.write(esc + "\n")


def set_theme(name):
    """`spark theme NAME`: choose it in site.env, render the files that carry
    it (install.sh; micro and tmux with the shell layer on), write theme.env
    and console-colors, reload tmux; macOS also gets the Terminal profile.
    SPARK_NO_APPLY=1 (tests) writes the key and the two runtime files only:
    nothing outside $HOME/.config/spark, no tmux, no Terminal.app."""
    if name != "none" and name not in palettes():
        say("spark theme: no palette named %s -- one of: none %s" % (name, " ".join(palettes())))
        return 2
    from . import site
    site.set_keys(SITE_THEME=name)
    if os.environ.get("SPARK_NO_APPLY"):
        write_runtime(name)
        return 0
    rc, out = run(["sh", os.path.join(REPO, "install.sh")], timeout=120)
    for line in out.splitlines():
        if not line.startswith("ok ") and not line.endswith("to do") and line != "Nothing to do":
            say("       " + line)
    if rc != 0:
        say("spark theme: install.sh failed -- sh %s says why" % os.path.join(REPO, "install.sh"))
        return 1
    write_runtime(name)
    rc, _ = run(["tmux", "list-sessions"])
    if rc == 0:
        run(["tmux", "source-file", os.path.join(HOME, ".tmux.conf")])
        say("ok     tmux         reloaded")
    if IS_MAC:
        profile(config.load(), False)
    from . import check
    check.refresh()
    say("open a new shell for the prompt colours (exec $SHELL); a running micro: reopen it")
    return 0


USAGE = """%s theme -- the palette SITE_THEME chose

  spark theme                  the palettes, and which one is current
  spark theme NAME             choose one (or none): site.env, tmux, starship,
                               btop, theme.env
  spark theme show             the current palette's colours
  spark theme profile          macOS: a Terminal.app profile, imported, default
""" % MARK


def main(argv):
    cfg = config.load()
    if not argv or argv[0] in ("list", "status"):
        return table(cfg)
    if argv[0] in ("-h", "--help", "help"):
        say(USAGE.rstrip())
        return 0
    if argv[0] == "profile":
        return profile(cfg, "--dry-run" in argv[1:])
    if argv[0] == "show":
        return show(cfg)
    if argv[0] == "none" or argv[0] in palettes():
        return set_theme(argv[0])
    say(USAGE.rstrip())
    return 2
