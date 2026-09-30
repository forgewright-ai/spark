# spark.handback -- the look leaves core (v1.62): what an older spark
# painted on this machine goes back as it was, once.
#
# The console palette (VGA again, the spark-console unit gone), the
# console font (its lines from the .spark-orig copy), the login screen
# (/etc/motd and /etc/issue from their .orig, 10-uname runnable again), a
# quiet boot (spark's GRUB drop-in, the Arch UKI drop-in and splash mark,
# Void's marked lines) and Terminal.app's spark-* profiles. Each step finds
# spark's own files and marks, so a machine that never had them does
# nothing, and root is asked only for what is there.
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

from . import CONFIG_DIR, IS_MAC, is_wsl, run, say

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

LINE_MARK = " #spark-quiet#"       # the end of each line spark appended (Void)
SPLASH_MARK = "#spark-quiet# "     # the start of the preset line spark commented (Arch UKI)
CURSOR_ON = "\033[?25h"            # all the /etc/issue a quiet login left
# the kernel's own sixteen: what a running VT gets back
VGA = ["#000000", "#aa0000", "#00aa00", "#aa5500", "#0000aa", "#aa00aa", "#00aaaa", "#aaaaaa",
       "#555555", "#ff5555", "#55ff55", "#ffff55", "#5555ff", "#ff55ff", "#55ffff", "#ffffff"]
# the console font's file per shape: its font keys and its redraw
FONT_FILES = ((CONSOLE_SETUP, ("FONTFACE", "FONTSIZE"), "setupcon --force"),
              (VCONSOLE, ("FONT",), "systemctl restart systemd-vconsole-setup"),
              (RCCONF, ("FONT",), "setfont"))


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
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _stage(ctx, tmp, path, text):
    """The new text of a root-owned file, written where root's cp reads
    it; '' in a dry run (nothing is written)."""
    if ctx.dry:
        return ""
    fd, staged = tempfile.mkstemp(dir=tmp, prefix=os.path.basename(path) + ".")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
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


def unmarked(text):
    """text without the lines spark appended (each ends with the mark). Pure."""
    return "".join(l for l in text.splitlines(True) if not l.rstrip("\n").endswith(LINE_MARK))


# ---------------------------------------------------------------- the steps
def palette(ctx, tmp):
    """The console palette: this VT and the kernel's defaults back to VGA,
    the boot unit gone, spark's palette files gone. /etc/rc.local was
    yours: a line there naming them is said, never edited."""
    files = [p for p in (CONSOLE_COLORS, CONSOLE_COLORS + ".rgb") if os.path.exists(p)]
    unit = os.path.exists(CONSOLE_UNIT)
    if not files and not unit:
        return False
    if not IS_MAC and not is_wsl():
        if not ctx.dry and os.environ.get("TERM") == "linux":
            try:
                with open("/dev/tty", "w") as tty:
                    tty.write("".join("\033]P%x%s" % (i, h[1:]) for i, h in enumerate(VGA)))
            except OSError:
                pass
        if shutil.which("setvtrgb"):
            ctx.root(WHAT, ["setvtrgb", "vga"], "the console palette is the kernel's VGA again")
        if unit:
            ctx.root(WHAT, ["sh", "-c", "systemctl disable spark-console.service >/dev/null 2>&1; rm -f %s && "
                             "{ systemctl daemon-reload >/dev/null 2>&1 || true; }" % shlex.quote(CONSOLE_UNIT)],
                     "spark-console.service is disabled and removed",
                     "sudo systemctl disable spark-console.service; sudo rm -f %s" % CONSOLE_UNIT)
        if "console-colors" in (_read(RC_LOCAL) or ""):
            ctx.row("todo", WHAT, "%s still paints spark's old palette at boot: its setvtrgb line is yours to delete" % RC_LOCAL)
    if ctx.dry:
        ctx.row("would", WHAT, "spark's palette files leave ~/.config/spark (console-colors)")
    else:
        for p in files:
            os.remove(p)
        ctx.row("ok", WHAT, "spark's palette files left ~/.config/spark (console-colors)")
    return True


def font(ctx, tmp):
    """The console font: the font lines of the file spark set go back to
    what its .spark-orig copy holds, the copy goes, the console redraws."""
    found = False
    for path, keys, redraw in FONT_FILES:
        orig = path + ".spark-orig"
        old, cur = _read(orig), _read(path)
        if IS_MAC or old is None:
            continue
        found = True
        staged = _stage(ctx, tmp, path, font_restored(cur, old, keys) if cur is not None else old)
        ctx.root(WHAT, ["sh", "-c", "%s && rm -f %s && { %s >/dev/null 2>&1 || true; }"
                        % (_cp(staged, path), shlex.quote(orig), redraw)],
                 "the console font is back as it was (%s)" % path,
                 "put the font lines of %s back into %s, then sudo %s" % (orig, path, redraw))
    return found


def login(ctx, tmp):
    """The login screen: /etc/motd and /etc/issue from their .orig (an
    issue spark left holding only the cursor escape empties), and the
    kernel line in the motd runnable again."""
    motd_o, issue_o = MOTD + ".orig", ISSUE + ".orig"
    spark_issue = (_read(ISSUE) or "").rstrip("\n") == CURSOR_ON
    if IS_MAC or not (os.path.exists(motd_o) or os.path.exists(issue_o) or spark_issue):
        return False
    q = shlex.quote
    steps = []
    if os.path.exists(motd_o):
        steps.append("cp %s %s && rm -f %s" % (q(motd_o), q(MOTD), q(motd_o)))
    if os.path.exists(issue_o):
        steps.append("cp %s %s && rm -f %s" % (q(issue_o), q(ISSUE), q(issue_o)))
    elif spark_issue:
        steps.append(": > %s" % q(ISSUE))
    if os.path.isfile(UNAME_MOTD) and not os.access(UNAME_MOTD, os.X_OK):
        steps.append("chmod +x %s" % q(UNAME_MOTD))
    ctx.root(WHAT, ["sh", "-c", " && ".join(steps)],
             "the distro notice, the kernel line and the login banner are back (%s, %s)" % (MOTD, ISSUE),
             "sudo cp %s %s; sudo cp %s %s; sudo chmod +x %s" % (motd_o, MOTD, issue_o, ISSUE, UNAME_MOTD))
    return True


def boot(ctx, tmp):
    """A quiet boot, per shape, each by spark's own file or mark: the
    Debian GRUB drop-in (the user's /etc/default/grub is never edited);
    the Arch UKI drop-in and the preset's splash line spark commented;
    Void's marked lines in GRUB's file, rc.conf and the getty's conf."""
    if IS_MAC:
        return False
    q = shlex.quote
    found = False
    if os.path.exists(GRUB_DROPIN):
        found = True
        ctx.root(WHAT, ["sh", "-c", "rm -f %s && update-grub >/dev/null 2>&1" % q(GRUB_DROPIN)],
                 "GRUB's menu and the kernel's messages are back (spark's drop-in removed, update-grub)",
                 "sudo rm -f %s; sudo update-grub" % GRUB_DROPIN, timeout=600)
    presets = [p for p in sorted(glob.glob(os.path.join(MKINITCPIO_D, "*.preset")))
               if any(l.startswith(SPLASH_MARK) for l in (_read(p) or "").splitlines())]
    if os.path.exists(CMDLINE_DROPIN) or presets:
        found = True
        steps = ["rm -f %s" % q(CMDLINE_DROPIN)]
        for p in presets:
            text = "".join(l[len(SPLASH_MARK):] if l.startswith(SPLASH_MARK) else l
                           for l in _read(p).splitlines(True))
            steps.append(_cp(_stage(ctx, tmp, p, text), p))
        steps.append("mkinitcpio -P >/dev/null 2>&1")
        ctx.root(WHAT, ["sh", "-c", " && ".join(steps)],
                 "the kernel's messages and the splash are back (spark's cmdline.d drop-in removed, mkinitcpio -P)",
                 "sudo rm -f %s; delete '%s' from the preset's options line; sudo mkinitcpio -P"
                 % (CMDLINE_DROPIN, SPLASH_MARK.strip()), timeout=600)
        # spark set systemd-boot's wait to 0 and never kept the value before
        ctx.row("todo", WHAT, "the boot menu's wait stays as spark set it (timeout 0 in /boot/loader/loader.conf): "
                              "the value before was not recorded, so set it back by hand if you want the menu")
    marked = [p for p in (DEFAULT_GRUB, RCCONF, GETTY_CONF)
              if any(l.endswith(LINE_MARK) for l in (_read(p) or "").splitlines())]
    if marked:
        found = True
        steps = [_cp(_stage(ctx, tmp, p, unmarked(_read(p))), p) for p in marked]
        if DEFAULT_GRUB in marked:
            steps.append("update-grub >/dev/null 2>&1")
        ctx.root(WHAT, ["sh", "-c", " && ".join(steps)],
                 "GRUB's menu, the kernel's messages, runit's lines and the getty are as Void ships them "
                 "(spark's marked lines removed from %s)" % ", ".join(marked),
                 "sudo sed -i '/%s$/d' %s; sudo update-grub" % (LINE_MARK, " ".join(marked)), timeout=600)
    return found


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
    """macOS: every spark-* profile leaves Terminal.app's preferences (a
    default or startup setting that named one is Basic again) and the
    .terminal files spark wrote go. Open windows keep their look."""
    if not IS_MAC:
        return False
    files = glob.glob(os.path.join(CONFIG_DIR, "spark-*.terminal"))
    path = os.path.join(tmp, "terminal")
    prefs = _terminal_prefs(path)
    ws = prefs.get("Window Settings")
    gone = sorted(k for k in ws if k.startswith("spark-")) if isinstance(ws, dict) else []
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
            if str(prefs.get(key, "")).startswith("spark-"):
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
    when nothing is left); an apply prints what it did, then one line."""
    dry = "--dry-run" in argv
    if walk(Ctx(dry)) and not dry:
        say("the look is off this machine now")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
