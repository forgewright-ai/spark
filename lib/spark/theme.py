# spark.theme -- the chosen palette, and the one place it cannot be
# symlinked into: Terminal.app on macOS, whose profiles are archived NSColor
# objects inside a plist. `spark theme profile` writes and imports one from
# the palette; on Linux the emulator is the user's, so it prints the palette
# for them to apply.

import os
import plistlib
import subprocess

from . import CONFIG_DIR, HOME, IS_MAC, MARK, REPO, SITE_ENV, config, glyph, run, say



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
         "columnCount": 120, "rowCount": 36, "useOptionAsMetaKey": True}
    for i, k in enumerate(keys):
        d["ANSI%sColor" % k] = ns_color(pal["THEME_ANSI_%d" % i])
    return d


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
        say("  %-18s %-34s %s" % (p, notes.get(p, ""), "current" if p == cfg.theme else ""))
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
    return 0


def profile(cfg, dry):
    pal = palette(cfg)
    if not pal:
        say("skip   profile      SITE_THEME=none")
        return 0
    if not IS_MAC:
        say("skip   profile      not macOS: apply %s in your terminal emulator's settings" % os.path.join(CONFIG_DIR, "theme.env"))
        return 0
    name = "spark-" + cfg.theme
    path = os.path.join(CONFIG_DIR, name + ".terminal")
    want = plistlib.dumps(profile_dict(name, pal, cfg.font_face, cfg.font_size))
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
    if have == want and imported and is_default:
        say("ok     profile      Terminal.app profile %s is the default" % name)
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
    if not imported:
        # `open` hands the file to Terminal.app, which adds the profile
        subprocess.run(["open", "-g", path], check=False)
    for key in ("Default Window Settings", "Startup Window Settings"):
        run(["defaults", "write", "com.apple.Terminal", key, "-string", name])
    say("ok     profile      %s written, imported and set as default (new windows use it)" % name)
    return 0


def palettes():
    try:
        return sorted(f[:-4] for f in os.listdir(os.path.join(REPO, "themes")) if f.endswith(".env"))
    except OSError:
        return []


def _set_site_theme(name):
    """Rewrite SITE_THEME= in site.env (append when absent); keep it 0600."""
    lines = []
    try:
        with open(SITE_ENV, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        pass
    done = False
    for i, line in enumerate(lines):
        if line.startswith("SITE_THEME="):
            lines[i] = "SITE_THEME=" + name
            done = True
    if not done:
        lines.append("SITE_THEME=" + name)
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(SITE_ENV, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(SITE_ENV, 0o600)


def set_theme(name):
    """`spark theme NAME`: choose it in site.env, render the files that carry
    it, write theme.env, reload tmux; macOS also gets the Terminal profile."""
    if name != "none" and name not in palettes():
        say("spark theme: no palette named %s -- one of: none %s" % (name, " ".join(palettes())))
        return 2
    from . import site
    site.set_keys(SITE_THEME=name)
    rc, out = run(["sh", os.path.join(REPO, "install.sh")], timeout=120)
    for line in out.splitlines():
        if not line.startswith("ok ") and not line.endswith("to do") and line != "Nothing to do":
            say("       " + line)
    if rc != 0:
        say("spark theme: install.sh failed -- sh %s says why" % os.path.join(REPO, "install.sh"))
        return 1
    theme_env = os.path.join(CONFIG_DIR, "theme.env")
    if name == "none":
        try:
            os.remove(theme_env)
        except OSError:
            pass
    else:
        pal = config.theme_palette(name, REPO)
        order = ["THEME_BG", "THEME_FG", "THEME_ACCENT", "THEME_MUTED", "THEME_BTOP"] + ["THEME_ANSI_%d" % i for i in range(16)]
        with open(theme_env, "w", encoding="utf-8") as f:       # bootstrap's order, so it agrees
            f.write("".join("%s=%s\n" % (k, pal[k]) for k in order if k in pal))
    rc, _ = run(["tmux", "list-sessions"])
    if rc == 0:
        run(["tmux", "source-file", os.path.join(HOME, ".tmux.conf")])
        say("ok     tmux         reloaded")
    if IS_MAC:
        profile(config.load(), False)
    from . import check
    check.refresh()
    say("open a new shell for the prompt colours (exec $SHELL)")
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
    if not argv or argv[0] == "list":
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
