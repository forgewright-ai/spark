# spark.chaos -- rehearse the failures. `spark check --chaos` breaks a
# throwaway machine one known way at a time and proves the right row says
# so and its remedy heals it. --selftest proves a row CAN flip; --chaos
# proves the sentence the row prints under it is true.
#
# A scenario is four things: break, the row it is judged by, the status
# that row must reach, and the heal. The heal is the row's OWN remedy
# string wherever the remedy is a command -- so a remedy that names a
# renamed verb or a stale path stops being prose nobody executes. Where
# the remedy is prose (./bootstrap.sh, a doc reference), the scenario
# supplies the command and the report says it did.
#
# The machine is check's good fixture: a throwaway HOME, a stub
# repository, stub commands and a stub llama-server on loopback. Nothing
# here touches the real machine, reaches the network beyond loopback, or
# runs longer than its own timeout. A scenario that needs the real box
# (a service manager that restarts things, a real GPU, a real full disk)
# says so and is skipped unless --real.

import os
import subprocess
import sys
import tempfile
import time

from . import MARK, REPO, glyph, say
from .check import FAIL, GLYPH, NA, OK, WARN


class Scenario:
    __slots__ = ("name", "row", "expect", "want", "heal", "unhealed", "real", "fn", "doc")

    def __init__(self, name, row, expect, want, heal, unhealed, real, fn):
        self.name, self.row, self.expect = name, row, expect
        self.want, self.heal, self.unhealed = want, heal, unhealed
        self.real, self.fn = real, fn
        self.doc = " ".join((fn.__doc__ or "").split())


SCENARIOS = []


def scenario(row, expect, want="", heal="remedy", unhealed="", real=False):
    """Register one rehearsed failure. `row` is the check row that must
    notice it, `expect` the status it must reach (WARN for a CAPABILITY
    row, which never fails; NA where the truth is "the world stopped
    offering this"), `want` a substring its value must carry. `heal` is
    the literal string "remedy" (run what the row itself printed), a
    command, or None -- and None must say in `unhealed` why nothing here
    can run the remedy, so an unrehearsed half is visible, not silent."""
    assert heal or unhealed, "a scenario with no heal must say why"
    def deco(fn):
        SCENARIOS.append(Scenario(fn.__name__[6:].replace("_", "-"), row,
                                  expect, want, heal, unhealed, real, fn))
        return fn
    return deco


class Machine:
    """One throwaway machine, built from check's good fixture. A scenario
    gets this: paths to break, `spark` to run, and `row()` to ask."""

    def __init__(self, root, stub_url=""):
        from . import check
        self.root = root
        self.stub_url = stub_url
        self.env = check.make_fixture(root, True, stub_url, real_spark=True)
        # a fixture must never apply itself onto the real machine, and
        # never leave a background refresh writing into a HOME that is
        # about to be deleted
        self.env["SPARK_NO_APPLY"] = "1"
        self.env["SPARK_NO_REFRESH"] = "1"
        # make_fixture keeps its own git identity to itself; a scenario
        # that commits (the git row's) needs one of its own
        self.env.update({"GIT_AUTHOR_NAME": "chaos", "GIT_AUTHOR_EMAIL": "chaos@fixture",
                         "GIT_COMMITTER_NAME": "chaos", "GIT_COMMITTER_EMAIL": "chaos@fixture"})
        self.home = os.path.join(root, "home")
        self.repo = os.path.join(root, "repo")
        self.bin = os.path.join(root, "bin")
        self.cfg = os.path.join(self.home, ".config", "spark")
        self.state = os.path.join(self.home, ".local", "state", "spark")
        self.models = os.path.join(self.home, ".local", "share", "spark", "models")
        self.notes = []

    def note(self, s):
        """One line the report prints under the scenario: what the break
        proved beyond the row itself."""
        self.notes.append(s)

    def spark(self, *args, **kw):
        """Run the real spark against this machine. (rc, output)."""
        argv = [sys.executable, os.path.join(REPO, "bin", "spark")] + list(args)
        return self._run(argv, kw.get("timeout", 120))

    def sh(self, cmd, timeout=120):
        """Run a shell command against this machine -- a remedy, verbatim
        as the row printed it. (rc, output)."""
        return self._run(["sh", "-c", cmd], timeout, cwd=self.repo)

    def _run(self, argv, timeout, cwd=None):
        try:
            p = subprocess.run(argv, env=self.env, cwd=cwd, capture_output=True,
                               text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return 124, "timed out after %ss" % timeout
        return p.returncode, p.stdout + p.stderr

    def row(self, name):
        """One row of `spark check`, by name: (status, value, remedy)."""
        rc, out = self.spark("check", "--porcelain", "--fresh", name)
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) == 5 and parts[2] == name:
                return parts[1], parts[3], parts[4]
        return "missing", "no %s row: %s" % (name, out.strip()[-200:] or "no output"), ""

    def git(self, *args):
        return self._run(["git", "-C", self.repo] + list(args), 30)

    def commit(self, message, tag=""):
        """A commit on the fixture repository, pushed, so the git row
        stays clean and level -- the scenario breaks it on purpose, not
        by accident. Returns "" or why it could not."""
        for args in (("add", "-A"), ("commit", "-q", "-m", message),
                     ("tag", tag) if tag else ("rev-parse", "HEAD"),
                     ("push", "-q", "origin", "main")):
            rc, out = self.git(*args)
            if rc != 0:
                return "git %s: %s" % (args[0], out.strip()[-200:])
        return ""


# ------------------------------------------------------------- scenarios
@scenario(row="git", expect=WARN, want="is out", heal="remedy")
def chaos_tags_behind(m):
    """A release clone three tags behind: the git row names the newest,
    and `spark update` moves it."""
    for tag in ("v1.2", "v1.3"):
        with open(os.path.join(m.repo, ".fixture-" + tag), "w") as f:
            f.write(tag + "\n")
        why = m.commit("fixture " + tag, tag)
        if why:
            return why
    rc, _ = m.git("checkout", "-q", "--detach", "v1.0")
    if rc != 0:
        return "could not detach the fixture clone at v1.0"
    return ""


@scenario(row="models", expect=WARN, want="sha256 mismatch", heal=None,
          unhealed="the remedy re-downloads the file: a network this "
                   "fixture does not have")
def chaos_truncated_model(m):
    """A model file truncated on disk: the models row says sha256
    mismatch, and `spark model verify` names the file."""
    path = os.path.join(m.models, "fixture.gguf")
    with open(path, "r+") as f:
        f.truncate(100)
    rc, out = m.spark("model", "verify")
    if rc == 0:
        return "spark model verify exited 0 on a truncated file"
    if "fixture" not in out.lower():
        return "spark model verify did not name the file: %r" % out.strip()[-200:]
    m.note("spark model verify exits %d and names the file" % rc)
    return ""


# ---------------------------------------------------------------- runner
def _fit(s, budget):
    """One line, cut at a word -- the report's own width, as every other
    value spark prints."""
    if len(s) <= budget:
        return s
    return s[:budget].rsplit(" ", 1)[0] + glyph("cut")


def _judge(m, sc):
    """Break, ask the row, heal, ask again. Returns (ok, [lines])."""
    lines = []
    why = sc.fn(m)
    if why:
        return False, ["the break did not take: " + why]
    status, value, remedy = m.row(sc.row)
    if status != sc.expect:
        return False, ["%s is %s, not %s: %s" % (sc.row, status, sc.expect, value)]
    if sc.want and sc.want not in value:
        return False, ["%s says %r, which does not carry %r" % (sc.row, value, sc.want)]
    lines.append("%s %s: %s" % (sc.row, status, value))
    for n in m.notes:
        lines.append(n)
    if sc.heal is None:
        lines.append("not healed here: " + sc.unhealed)
        return True, lines
    if sc.heal == "remedy":
        if not remedy:
            return False, lines + ["the row prints no remedy to run"]
        cmd, how = remedy, "its own remedy"
    else:
        cmd, how = sc.heal, "the scenario's heal (the row's remedy is prose)"
    rc, out = m.sh(cmd)
    lines.append("heal, %s: %s" % (how, cmd))
    if rc != 0:
        return False, lines + ["the heal exited %d: %s" % (rc, out.strip()[-300:])]
    status, value, _r = m.row(sc.row)
    if status != OK:
        return False, lines + ["healed, but %s is %s: %s" % (sc.row, status, value)]
    lines.append("%s ok: %s" % (sc.row, value))
    return True, lines


def run(real=False, only=()):
    """Every scenario, each on its own throwaway machine. Exit 0 iff every
    one of them rehearsed."""
    from .check import _stub_server
    say("%s check --chaos" % MARK)
    srv, stub_url = _stub_server()
    bad = skipped = 0
    try:
        for sc in SCENARIOS:
            if only and sc.name not in only:
                continue
            if sc.real and not real:
                say("  %s %-16s needs a real box (--chaos --real)" % (GLYPH[NA], sc.name))
                skipped += 1
                continue
            t0 = time.time()
            with tempfile.TemporaryDirectory(prefix="spark-chaos-") as tmp:
                root = os.path.join(tmp, sc.name)
                os.makedirs(root)
                try:
                    m = Machine(root, stub_url)
                    passed, lines = _judge(m, sc)
                except Exception as e:      # a crashed scenario is a failed one
                    from . import log_exc
                    log_exc("chaos " + sc.name)
                    passed, lines = False, ["crashed: %s" % e]
            bad += not passed
            say("  %s %-16s %s" % (GLYPH[OK] if passed else GLYPH[FAIL], sc.name,
                                    _fit(sc.doc, 58 - len(" (%.1fs)" % 0)) + " (%.1fs)" % (time.time() - t0)))
            for line in lines:
                say("      %s %s" % (glyph("arrow"), line))
    finally:
        srv.shutdown()
    tail = " (%d need a real box)" % skipped if skipped else ""
    if bad:
        say("  %d scenario%s did not rehearse%s" % (bad, "" if bad == 1 else "s", tail))
    else:
        say("  every scenario rehearsed%s" % tail)
    return 1 if bad else 0
