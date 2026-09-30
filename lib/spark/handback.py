# spark.handback -- the look leaves core (v1.62): what an older spark
# painted on this machine goes back as it was, once.
#
# The console palette (VGA again, the spark-console unit gone), the
# console font (its lines from the .spark-orig copy), the login screen
# (/etc/motd and /etc/issue from their .orig, 10-uname runnable again), a
# quiet boot (spark's GRUB drop-in, the Arch UKI drop-in and splash mark,
# Void's marked lines) and Terminal.app's spark profiles. Each step finds
# spark's own files and marks, so a machine that never had them does
# nothing, and root is asked only for what is there.
#
# Only what spark itself made (v1.63), each by spark's own record: its
# exact file names, its own marks, its .orig and .spark-orig copies, the
# profile names it wrote. Another tool may paint the same things under
# names of its own, and a login screen that looks quiet with no .orig of
# spark's beside it is not spark's: all of that stays as it is.
#
# One undo, two callers: bootstrap's `handback` row (`python3 -m
# spark.handback [--dry-run]`, every `spark update`) and `spark
# uninstall`, whose Ctx is one of these. Nothing here imports the look's
# old modules: they are gone. The /etc paths take bootstrap's SPARK_ETC_*
# seams, so the tests pin a fixture.

import glob
import os
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

from . import CONFIG_DIR, IS_MAC, STATE_DIR, is_wsl, run, say

WHAT = "handback"


def _etc(key, default):
    return os.environ.get(key) or default


CONSOLE_COLORS = os.path.join(CONFIG_DIR, "console-colors")
CONSOLE_UNIT = _etc("SPARK_ETC_CONSOLE_UNIT", "/etc/systemd/system/spark-console.service")
RC_LOCAL = _etc("SPARK_ETC_RC_LOCAL", "/etc/rc.local")
CONSOLE_SETUP = _etc("SPARK_ETC_CONSOLE_SETUP", "/etc/default/console-setup")
VCONSOLE = _etc("SPARK_ETC_VCONSOLE", "/etc/vconsole.conf")
RCCONF = _etc("SPARK_ETC_RCCONF", "/etc/rc.conf")
MOTD = _etc("SPARK_ETC_MOTD", "/etc/motd")
ISSUE = _etc("SPARK_ETC_ISSUE", "/etc/issue")
UNAME_MOTD = _etc("SPARK_ETC_UNAME_MOTD", "/etc/update-motd.d/10-uname")
GRUB_DROPIN = _etc("SPARK_ETC_GRUB_DROPIN", "/etc/default/grub.d/zz-spark-quiet.cfg")
DEFAULT_GRUB = _etc("SPARK_ETC_DEFAULT_GRUB", "/etc/default/grub")
GETTY_CONF = _etc("SPARK_ETC_GETTY_CONF", "/etc/sv/agetty-tty1/conf")
MKINITCPIO_D = _etc("SPARK_ETC_MKINITCPIO_D", "/etc/mkinitcpio.d")
CMDLINE_DROPIN = _etc("SPARK_ETC_CMDLINE_DROPIN", "/etc/cmdline.d/zz-spark-quiet.conf")
TERMINAL_DOMAIN = _etc("SPARK_TERMINAL_DOMAIN", "com.apple.Terminal")
# a boot rebuild that has not held yet: its kinds, one per line, until it runs
REBUILD_MARK = os.path.join(STATE_DIR, "handback-rebuild")
REBUILDS = {"grub": (["update-grub"], "update-grub ran: GRUB's menu and the kernel's messages are back"),
            "uki": (["mkinitcpio", "-P"], "mkinitcpio -P ran: the kernel's messages and the splash are back")}

LINE_MARK = " #spark-quiet#"       # the end of each line spark appended (Void)
SPLASH_MARK = "#spark-quiet# "     # the start of the preset line spark commented (Arch UKI)
CURSOR_ON = "\033[?25h"            # all the /etc/issue a quiet login left
# the Terminal.app profiles spark made: spark-<palette>, one of the nine
# palettes it shipped (v1.61's themes/), or a name whose .terminal file it
# wrote in ~/.config/spark. Any other spark-<word> is another tool's.
SHIPPED_PALETTES = ("catppuccin-mocha", "dracula", "everforest-dark", "gruvbox-dark", "nord",
                    "rose-pine", "selenized-dark", "solarized-light", "tokyonight-night")
PALETTE_ROWS = "/spark/console-colors"   # what a boot line naming spark's palette files holds
# the kernel's own sixteen: what a running VT gets back
VGA = ["#000000", "#aa0000", "#00aa00", "#aa5500", "#0000aa", "#aa00aa", "#00aaaa", "#aaaaaa",
       "#555555", "#ff5555", "#55ff55", "#ffff55", "#5555ff", "#ff55ff", "#55ffff", "#ffffff"]
# the console font's file per shape: its font keys and its redraw (Void
# has none: a bare setfont is not the kernel's font, the next boot is)
FONT_FILES = ((CONSOLE_SETUP, ("FONTFACE", "FONTSIZE"), "setupcon --force"),
              (VCONSOLE, ("FONT",), "systemctl restart systemd-vconsole-setup"),
              (RCCONF, ("FONT",), None))


class Ctx(object):
    """What the undo speaks through: a row and a root command. dry makes
    every change a `would` row and runs nothing."""

    def __init__(self, dry):
        self.dry = dry
        self.todo = []          # (what, the manual line)

    def row(self, status, what, detail=""):
        if self.dry and status == "ok":
            status = "would"
        say("%-6s %-12s %s" % (status, what, detail))
        if status == "todo":
            self.todo.append((what, detail))

    def root(self, what, cmd, done, manual=None, timeout=120):
        """Run cmd as root (sudo): a `would` row when dry, `ok` when it ran,
        `todo` with the manual line when sudo refused or is absent."""
        manual = manual or "sudo " + " ".join(cmd)
        if self.dry:
            self.row("would", what, done + " (sudo)")
            return False
        argv = cmd if os.getuid() == 0 else None
        if argv is None and shutil.which("sudo"):
            argv = ["sudo"] + ([] if sys.stdin.isatty() else ["-n"]) + cmd
        if argv:
            try:
                rc = subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout).returncode
            except (OSError, subprocess.TimeoutExpired):
                rc = 1
            if rc == 0:
                self.row("ok", what, done)
                return True
        self.row("todo", what, manual)
        return False


def _read(path):
    """A root file's text, byte for byte (latin-1 maps each byte to one
    character and back, newlines as they are); None when unreadable."""
    try:
        with open(path, encoding="latin-1", newline="") as f:
            return f.read()
    except OSError:
        return None


def _lines(text):
    """text's lines, each with its newline: split at newlines only
    (splitlines also splits at bytes a latin-1 read makes breaks). Pure."""
    return re.findall(r"[^\n]*\n|[^\n]+", text)


def _stage(ctx, tmp, path, text):
    """The new text of a root-owned file, written where root's cp reads
    it; '' in a dry run (nothing is written)."""
    if ctx.dry:
        return ""
    fd, staged = tempfile.mkstemp(dir=tmp, prefix=os.path.basename(path) + ".")
    with os.fdopen(fd, "w", encoding="latin-1", newline="") as f:
        f.write(text)
    return staged


def _cp(staged, path):
    return "cp %s %s" % (shlex.quote(staged), shlex.quote(path))


def font_restored(text, orig, keys):
    """text with its console-font lines as orig had them: the i-th KEY=
    (or #KEY=) line of text becomes orig's i-th, and one orig lacked
    (spark appended it) goes. Every other line stays as it is now. Pure."""
    def key(line):
        return next((k for k in keys if re.match(r"#?%s=" % re.escape(k), line)), None)
    olds = {k: [l for l in orig.split("\n") if key(l) == k] for k in keys}
    out = []
    for line in text.split("\n"):
        k = key(line)
        if k is None:
            out.append(line)
        elif olds[k]:
            out.append(olds[k].pop(0))
    return "\n".join(out)


def profile_names(written=()):
    """The Terminal.app profile names spark made: spark- and a palette it
    shipped, and the names of the .terminal files it wrote (written). Pure."""
    return {"spark-" + n for n in SHIPPED_PALETTES} | set(written)


def _written_profiles():
    """The .terminal files spark wrote (~/.config/spark/spark-*.terminal),
    by the profile name each carries."""
    return [os.path.basename(p)[:-len(".terminal")] for p in glob.glob(os.path.join(CONFIG_DIR, "spark-*.terminal"))]


def unmarked(text):
    """text without the lines spark appended (each ends with the mark). Pure."""
    return "".join(l for l in _lines(text) if not l.rstrip("\r\n").endswith(LINE_MARK))


# ---------------------------------------------------------------- the steps
def palette(ctx, tmp):
    """The console palette: this VT and the kernel's defaults back to VGA,
    the boot unit gone, then spark's palette files gone (kept while a
    root step is left to do). /etc/rc.local was yours: a line there
    naming them is said, never edited."""
    files = [p for p in (CONSOLE_COLORS, CONSOLE_COLORS + ".rgb") if os.path.exists(p)]
    unit = os.path.exists(CONSOLE_UNIT)
    if not files and not unit:
        return False
    held = True
    if not IS_MAC and not is_wsl():
        if not ctx.dry and os.environ.get("TERM") == "linux":
            try:
                with open("/dev/tty", "w") as tty:
                    tty.write("".join("\033]P%x%s" % (i, h[1:]) for i, h in enumerate(VGA)))
            except OSError:
                pass
        if shutil.which("setvtrgb"):
            held = ctx.root(WHAT, ["setvtrgb", "vga"], "the console palette is the kernel's VGA again") and held
        if unit:
            held = ctx.root(WHAT, ["sh", "-c", "systemctl disable spark-console.service >/dev/null 2>&1; rm -f %s && "
                                   "{ systemctl daemon-reload >/dev/null 2>&1 || true; }" % shlex.quote(CONSOLE_UNIT)],
                            "spark-console.service is disabled and removed",
                            "sudo systemctl disable spark-console.service; sudo rm -f %s" % CONSOLE_UNIT) and held
        if any(PALETTE_ROWS in l for l in _lines(_read(RC_LOCAL) or "")):
            ctx.row("todo", WHAT, "%s still paints spark's old palette at boot: its setvtrgb line is yours to delete" % RC_LOCAL)
    if ctx.dry:
        ctx.row("would", WHAT, "spark's palette files leave ~/.config/spark (console-colors)")
    elif held:
        for p in files:
            os.remove(p)
        ctx.row("ok", WHAT, "spark's palette files left ~/.config/spark (console-colors)")
    return True


def font(ctx, tmp):
    """The console font: the font lines of the file spark set go back to
    what its .spark-orig copy holds, the copy goes, the console redraws
    (Void's at the next boot)."""
    found = False
    for path, keys, redraw in FONT_FILES:
        orig = path + ".spark-orig"
        old, cur = _read(orig), _read(path)
        if IS_MAC or old is None:
            continue
        found = True
        staged = _stage(ctx, tmp, path, font_restored(cur, old, keys) if cur is not None else old)
        script = "%s && rm -f %s" % (_cp(staged, path), shlex.quote(orig))
        if redraw:
            ctx.root(WHAT, ["sh", "-c", "%s && { %s >/dev/null 2>&1 || true; }" % (script, redraw)],
                     "the console font is back as it was (%s)" % path,
                     "put the font lines of %s back into %s, then sudo %s" % (orig, path, redraw))
        else:
            ctx.root(WHAT, ["sh", "-c", script],
                     "the console font lines are back as they were (%s): the console font returns at the next boot" % path,
                     "put the font lines of %s back into %s, then reboot" % (orig, path))
    return found


def login(ctx, tmp):
    """The login screen, only by spark's own record: /etc/motd and
    /etc/issue from their .orig while the live file is still spark's (an
    empty motd, an issue holding only the cursor escape), and the kernel
    line in the motd runnable again with it. A live file changed since is
    yours: only its stale .orig goes. No .orig, not spark's: an issue
    holding the cursor escape alone is another tool's quiet login, and
    it stays as it is, the motd and 10-uname with it."""
    motd_o, issue_o = MOTD + ".orig", ISSUE + ".orig"
    spark_motd = _read(MOTD) == ""
    spark_issue = (_read(ISSUE) or "").rstrip("\n") == CURSOR_ON
    if IS_MAC or not (os.path.exists(motd_o) or os.path.exists(issue_o)):
        return False
    q = shlex.quote
    steps, manual, back = [], [], []
    for orig, path, spark in ((motd_o, MOTD, spark_motd), (issue_o, ISSUE, spark_issue)):
        if not os.path.exists(orig):
            continue
        if spark:
            steps.append("cp %s %s" % (q(orig), q(path)))
            manual.append("sudo cp %s %s" % (orig, path))
            back.append(path)
        steps.append("rm -f %s" % q(orig))
        manual.append("sudo rm -f %s" % orig)
    if MOTD in back and os.path.isfile(UNAME_MOTD) and not os.access(UNAME_MOTD, os.X_OK):
        steps.append("chmod +x %s" % q(UNAME_MOTD))
        manual.append("sudo chmod +x %s" % UNAME_MOTD)
    done = ("the login screen is back as it was (%s)" % ", ".join(back) if back else
            "spark's stale copies of the login screen are gone; yours stays as it is")
    ctx.root(WHAT, ["sh", "-c", " && ".join(steps)], done, "; ".join(manual))
    return True


def _pending():
    """The boot rebuilds a run before left undone (REBUILD_MARK)."""
    try:
        with open(REBUILD_MARK, encoding="utf-8") as f:
            return {k for k in f.read().split() if k in REBUILDS}
    except OSError:
        return set()


def _mark(kinds):
    """REBUILD_MARK holds kinds, or goes when there are none."""
    if kinds:
        os.makedirs(os.path.dirname(REBUILD_MARK), exist_ok=True)
        with open(REBUILD_MARK, "w", encoding="utf-8") as f:
            f.write("".join(k + "\n" for k in sorted(kinds)))
    else:
        try:
            os.remove(REBUILD_MARK)
        except OSError:
            pass


def boot(ctx, tmp):
    """A quiet boot, per shape, each by spark's own file or mark: the
    Debian GRUB drop-in (the user's /etc/default/grub is never edited);
    the Arch UKI drop-in and the preset's splash line spark commented;
    Void's marked lines in GRUB's file, rc.conf and the getty's conf.
    Then the rebuild (update-grub, mkinitcpio -P). REBUILD_MARK is
    written before the traces go and cleared when the rebuild held, so a
    rebuild that failed runs again next time."""
    if IS_MAC:
        return False
    q = shlex.quote
    steps = []          # (kind, argv, done, manual): spark's traces out
    if os.path.exists(GRUB_DROPIN):
        steps.append(("grub", ["rm", "-f", GRUB_DROPIN], "spark's GRUB drop-in is removed (%s)" % GRUB_DROPIN,
                      "sudo rm -f %s" % GRUB_DROPIN))
    presets = [p for p in sorted(glob.glob(os.path.join(MKINITCPIO_D, "*.preset")))
               if any(l.startswith(SPLASH_MARK) for l in _lines(_read(p) or ""))]
    if os.path.exists(CMDLINE_DROPIN) or presets:
        cmd = ["rm -f %s" % q(CMDLINE_DROPIN)]
        for p in presets:
            text = "".join(l[len(SPLASH_MARK):] if l.startswith(SPLASH_MARK) else l for l in _lines(_read(p)))
            cmd.append(_cp(_stage(ctx, tmp, p, text), p))
        steps.append(("uki", ["sh", "-c", " && ".join(cmd)],
                      "spark's cmdline.d drop-in is removed and the splash is unmarked",
                      "sudo rm -f %s; delete '%s' from the preset's options line" % (CMDLINE_DROPIN, SPLASH_MARK.strip())))
    marked = [p for p in (DEFAULT_GRUB, RCCONF, GETTY_CONF)
              if any(l.rstrip("\r\n").endswith(LINE_MARK) for l in _lines(_read(p) or ""))]
    if marked:
        steps.append(("grub" if DEFAULT_GRUB in marked else None,
                      ["sh", "-c", " && ".join(_cp(_stage(ctx, tmp, p, unmarked(_read(p))), p) for p in marked)],
                      "Void's boot lines are as it ships them (spark's marked lines removed from %s)"
                      % ", ".join(marked),
                      "sudo sed -i '/%s$/d' %s" % (LINE_MARK, " ".join(marked))))
    pending = _pending()
    if not steps and not pending:
        return False
    kinds = pending | {k for k, _, _, _ in steps if k}
    if not ctx.dry:
        _mark(kinds)
    left = set()        # kinds whose traces stayed: no rebuild yet
    for kind, argv, done, manual in steps:
        if not ctx.root(WHAT, argv, done, manual) and not ctx.dry:
            left.add(kind)
    if any(k == "uki" for k, _, _, _ in steps):
        # spark set systemd-boot's wait to 0 and never kept the value before
        ctx.row("todo", WHAT, "the boot menu's wait stays as spark set it (timeout 0 in /boot/loader/loader.conf): "
                              "the value before was not recorded, so set it back by hand if you want the menu")
    for kind in sorted(kinds - left):
        argv, done = REBUILDS[kind]
        if kind in pending:
            done += " (a retry: the last run's failed)"
        if ctx.root(WHAT, argv, done, timeout=600):
            kinds.discard(kind)
    if not ctx.dry:
        _mark(kinds)
    return True


def _terminal_prefs(path):
    """Terminal.app's preferences as a dict, {} when there are none.
    `defaults export` writes XML that carries the key map's ESC byte raw --
    which no XML parser accepts -- so plutil (lenient) turns it into a
    binary plist first."""
    xml, bin_ = path + ".export", path + ".bin"
    try:
        rc, _ = run(["defaults", "export", TERMINAL_DOMAIN, xml], timeout=10)
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


def terminal(ctx, tmp):
    """macOS: every profile spark made (profile_names: never a spark-<word>
    of another tool's) leaves Terminal.app's preferences (a default or
    startup setting that named one is Basic again) and the .terminal
    files spark wrote go. Open windows keep their look."""
    if not IS_MAC:
        return False
    files = glob.glob(os.path.join(CONFIG_DIR, "spark-*.terminal"))
    names = profile_names(_written_profiles())
    path = os.path.join(tmp, "terminal")
    prefs = _terminal_prefs(path)
    ws = prefs.get("Window Settings")
    gone = sorted(k for k in ws if k in names) if isinstance(ws, dict) else []
    if not gone and not files:
        return False
    done = "the spark profiles left Terminal.app; open windows keep their look until closed"
    if ctx.dry:
        ctx.row("would", WHAT, done)
        return True
    for f in files:
        os.remove(f)
    if gone:
        for k in gone:
            del ws[k]
        for key in ("Default Window Settings", "Startup Window Settings"):
            if str(prefs.get(key, "")) in names:
                prefs[key] = "Basic"
        with open(path + ".prefs", "wb") as f:
            plistlib.dump(prefs, f, fmt=plistlib.FMT_BINARY)
        rc, _ = run(["defaults", "import", TERMINAL_DOMAIN, path + ".prefs"], timeout=10)
        if rc != 0:
            ctx.row("todo", WHAT, "Terminal.app kept the spark profiles: delete them in Terminal > Settings > Profiles")
            return True
    ctx.row("ok", WHAT, done)
    return True


STEPS = (palette, font, login, boot, terminal)


def walk(ctx):
    """Every step, in order, each reading its files when it runs (rc.conf
    is the font's and the boot's). True when anything was left."""
    tmp = tempfile.mkdtemp(prefix="spark-handback-")
    try:
        found = False
        for step in STEPS:
            found = step(ctx, tmp) or found
        return found
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv):
    """bootstrap's handback row: `--dry-run` prints the would rows (nothing
    when nothing is left); an apply prints what it did, then one line
    when nothing is left to do."""
    dry = "--dry-run" in argv
    ctx = Ctx(dry)
    if walk(ctx) and not dry and not ctx.todo:
        say("the look is off this machine now")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
