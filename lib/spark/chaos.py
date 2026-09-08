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
# runs longer than its own timeout -- so the suite is a gate, not an
# errand. The rehearsals that need a real box (a unit restarting a
# killed server, a genuinely full disk) are the maintainer's, by hand,
# as the WSL pass is; ROADMAP.md says so.

import os
import re
import subprocess
import sys
import tempfile
import time

from . import MARK, REPO, glyph, say
from .check import FAIL, GLYPH, NA, OK, WARN
from .cli import ANSWER_MAX


class Scenario:
    __slots__ = ("name", "row", "expect", "want", "heal", "healed", "unhealed",
                 "mood", "fn", "doc")

    def __init__(self, name, row, expect, want, heal, healed, unhealed, mood, fn):
        self.name, self.row, self.expect = name, row, expect
        self.want, self.heal, self.healed, self.unhealed = want, heal, healed, unhealed
        self.mood, self.fn = mood, fn
        self.doc = " ".join((fn.__doc__ or "").split())


SCENARIOS = []


def scenario(row=None, expect=None, want="", heal="remedy", healed=OK,
             unhealed="", mood="ok"):
    """Register one rehearsed failure. `row` is the check row that must
    notice it, `expect` the status it must reach (WARN for a CAPABILITY
    row, which never fails; NA where the truth is "the world stopped
    offering this"), `want` a substring its value must carry. `heal` is
    the literal string "remedy" (run what the row itself printed), a
    command, or None -- and None must say in `unhealed` why nothing here
    can run the remedy, so an unrehearsed half is visible, not silent.
    `healed` is the status the row must reach after it (OK, or NA where
    the remedy's promise is to forget a thing, not to bring it back).
    `mood` is the brain this machine gets."""
    assert heal or unhealed, "a scenario with no heal must say why"
    assert row or unhealed, "a scenario with no row must say what it proves"
    def deco(fn):
        SCENARIOS.append(Scenario(fn.__name__[6:].replace("_", "-"), row, expect,
                                  want, heal, healed, unhealed, mood, fn))
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
        # nor may it reach the real machine's servers. A throwaway HOME is
        # not enough: the ports are not in it, so on a box that is actually
        # serving, 8080 answered the fixture's health probe (a `spark
        # serve` scenario then found itself "already serving") and `spark
        # stop` looked straight at the real llama-server's pid. Two ports
        # of its own, bound by nothing, so every probe here answers no.
        self.env["SPARK_PORT"] = str(_free_port())
        self.env["SPARK_FORGE_PORT"] = str(_free_port())
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
        self.brain = None
        self.notes = []

    def short(self, path):
        return "~" + path[len(self.home):] if path.startswith(self.home + "/") else path

    def note(self, s):
        """One line the report prints under the scenario: what the break
        proved beyond the row itself."""
        self.notes.append(s)

    def spark(self, *args, **kw):
        """Run the real spark against this machine. (rc, output)."""
        argv = [sys.executable, os.path.join(REPO, "bin", "spark")] + list(args)
        return self._run(argv, kw.get("timeout", 120), stdin=kw.get("stdin"))

    def sh(self, cmd, timeout=120):
        """Run a shell command against this machine -- a remedy, verbatim
        as the row printed it. (rc, output)."""
        return self._run(["sh", "-c", cmd], timeout, cwd=self.repo)

    def _run(self, argv, timeout, cwd=None, stdin=None):
        try:
            p = subprocess.run(argv, env=self.env, cwd=cwd, input=stdin or "",
                               capture_output=True, text=True, timeout=timeout)
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



# --------------------------------------------------------------- the brain
# A llama-server with a mood. The stub check's fixture carries answers
# GET only; a rehearsed failure needs a brain that can be slow, hang,
# cut a reply in half, answer rubbish -- and be killed mid-reply, which
# an in-process thread cannot be. So: a real process, on loopback.
BRAIN = r'''#!/usr/bin/env python3
import json, os, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer

MOOD = os.environ.get("MOOD", "ok")
# the fixture holds two: the api-token a llama-server wants and the
# forge-token a FORGE wants. This brain answers to both -- which one
# the client picks is the client's business, not the rehearsal's.
TOKENS = [t for t in os.environ.get("BRAIN_TOKENS", "").split(",") if t]
PORT = int(os.environ["BRAIN_PORT"])
LINE = {"kind": "cmd", "command": "echo rehearsed", "hint": "a rehearsed answer", "danger": False}
MODELS = {"data": [{"id": "fixture.gguf", "aliases": ["spark"], "status": {"value": "loaded"}},
                   {"id": "fixture-ember.gguf", "aliases": ["ember"], "status": {"value": "loaded"}}]}
seen = [0]


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self):
        if not TOKENS:
            return True
        return self.headers.get("Authorization") in ["Bearer " + t for t in TOKENS]

    def do_GET(self):
        if MOOD == "blackhole":                 # the LAN, cut: nothing comes back
            time.sleep(600)
            return
        if self.path == "/health":
            if MOOD == "loading":
                return self._send(503, b'{"status":"loading model"}')
            return self._send(200, b'{"status":"ok"}')
        if self.path == "/api/health":
            return self._send(200, json.dumps(
                {"status": "ok", "forge": True, "name": "chaos", "version": "0",
                 "model": "fixture.gguf", "upstream": "ok",
                 "models": {"spark": "loaded"}, "roles": {"spark": "fixture"}}).encode())
        if self.path.startswith("/v1/models") or self.path.startswith("/api/models"):
            if not self._authed():
                return self._send(401, b"{}")
            return self._send(200, json.dumps(MODELS).encode())
        self._send(404, b"{}")

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            body = {}
        if not self._authed():
            return self._send(401, b"{}")
        if MOOD in ("hang", "blackhole"):       # accepts, and never answers
            time.sleep(600)
            return
        if MOOD == "slow":
            time.sleep(float(os.environ.get("BRAIN_SLOW", "3")))
        stream = bool(body.get("stream"))
        if MOOD == "cut":                       # half a reply, then the wire dies
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream" if stream else "application/json")
            self.send_header("Content-Length", "40000")
            self.end_headers()
            half = (b'data: {"choices":[{"delta":{"content":"half an "}}]}\n\n'
                    if stream else b'{"choices":[{"message":{"content":"{\"kind\"')
            self.wfile.write(half)
            self.wfile.flush()
            self.close_connection = True
            return
        seen[0] += 1
        if MOOD == "garbage":
            # three ways a model betrays contract 4: prose where JSON was
            # asked for, nothing at all, and a well-formed answer 40 kB
            # long whose command carries newlines of its own
            content = ["a model that answers in prose, not JSON", "",
                       json.dumps({"kind": "cmd", "hint": "y" * 40000, "danger": False,
                                   "command": "echo one\necho two\n" + "z" * 40000})][(seen[0] - 1) % 3]
        else:
            content = json.dumps(LINE)
        if stream:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for piece in (content[i:i + 400] for i in range(0, max(len(content), 1), 400)):
                self.wfile.write(b"data: " + json.dumps(
                    {"choices": [{"delta": {"content": piece}}]}).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            self.close_connection = True
            return
        self._send(200, json.dumps({"choices": [{"message": {"content": content}}],
                                    "timings": {"predicted_per_second": 12.0}}).encode())


HTTPServer(("127.0.0.1", PORT), H).serve_forever()
'''


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Brain:
    """The moody llama-server, as a real process: startable, killable."""

    # the three the fixture holds: the api-token (a llama-server), the
    # forge-token (a FORGE, admin) and the box account's own login --
    # which of them a client sends is the client's business, not the
    # rehearsal's, so this brain answers to all three
    TOKENS = "stub-token,stub-forge-token,fixture-token"

    def __init__(self, root, mood="ok", tokens=TOKENS):
        path = os.path.join(root, "brain.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(BRAIN)
        self.port = _free_port()
        self.url = "http://127.0.0.1:%d" % self.port
        self.mood = mood
        env = dict(os.environ, MOOD=mood, BRAIN_PORT=str(self.port), BRAIN_TOKENS=tokens)
        self.p = subprocess.Popen([sys.executable, path], env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # ready = the port accepts, not /health answers: a blackhole
        # brain never answers anything, and is still up
        import socket
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=1).close()
                return
            except OSError:
                time.sleep(0.05)
        raise RuntimeError("the chaos brain never came up on %s" % self.url)

    def kill(self):
        """SIGKILL: the server dies where it stands, mid-reply."""
        self.p.kill()
        self.p.wait(timeout=10)

    def stop(self):
        if self.p.poll() is None:
            self.p.terminate()
            try:
                self.p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.p.kill()


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


@scenario(row="serve", expect=WARN, want="nothing answers", healed=NA, mood="cut")
def chaos_server_killed_mid_reply(m):
    """The server dies mid-reply: the answer fails cleanly, the turn is
    still on the thread, and the serve row says nothing answers."""
    t0 = time.time()
    rc, out = m.spark("what is 2+2?", timeout=60)
    took = time.time() - t0
    if rc == 0:
        return "a cut reply exited 0: %r" % out.strip()[-200:]
    if "Traceback" in out:
        return "a cut reply ended in a traceback: %s" % out.strip()[-300:]
    m.note("the cut reply failed in %.1fs, one line: %s"
           % (took, _fit(" ".join(out.split()), 60)))
    # the words were on the screen: a connection dying must not take the
    # question with it (forge.reply lands the partial, as a stop does)
    _rc, hist = m.spark("history")
    if "2+2" not in hist:
        return ("the cut turn left nothing on the thread: spark history says %r"
                % " ".join(hist.split())[-200:])
    m.note("the question is still on the thread the cut interrupted")
    m.brain.kill()                  # and now the server is gone for good
    return ""


@scenario(row="gpu", expect=NA, heal=None,
          unhealed="the GPU comes back when the hardware does: the row's "
                   "promise is to say so and let the CPU answer")
def chaos_gpu_taken_away(m):
    """The GPU taken away: the gpu row says so, never fails, and the line
    still answers on the CPU."""
    gone = os.path.join(m.root, "no-drm")
    os.makedirs(gone, exist_ok=True)
    m.env["SPARK_SYSFS_DRM"] = gone
    rc, out = m.spark("line", "--cwd", m.root, "--shell", "bash", stdin="how big is this dir?\n")
    if rc != 0 or not out.startswith(("cmd\t", "answer")):
        return "the line did not answer without a GPU: rc %d, %r" % (rc, out[:200])
    m.note("the line still answers: %s" % _fit(out.splitlines()[0], 60))
    return ""


@scenario(row="peer", expect=WARN, want="down", heal=None, mood="blackhole",
          unhealed="the LAN comes back when the cable does: the row's "
                   "promise is to say the peer is unreachable")
def chaos_lan_cut_on_a_client(m):
    """The LAN cut on a client: the peer row says down, and a question
    fails fast instead of hanging on a wire nobody answers."""
    m.env["SITE_AI_MODEL"] = "none"         # a client: nothing runs here
    m.env["SITE_PEER_AI_URL"] = m.brain.url
    budget = 30
    t0 = time.time()
    rc, out = m.spark("line", "--cwd", m.root, "--shell", "bash",
                      stdin="how big is this dir?\n", timeout=budget + 30)
    took = time.time() - t0
    if rc == 0:
        return "the line answered from a peer that never replied: %r" % out[:200]
    if took > budget:
        return "the line took %.0fs to give up: a cut LAN must fail fast" % took
    m.note("the line gives up in %.1fs (budget %ds): %s"
           % (took, budget, _fit(" ".join(out.split()), 55)))
    return ""


@scenario(heal=None, unhealed="a download that dies must leave nothing "
                              "behind, least of all on a full disk")
def chaos_full_disk_download(m):
    """A download that cannot be written: bootstrap refuses cleanly, and
    no .part file is left on the disk that was already full."""
    # a curl that writes a little and then fails the way a full disk
    # fails it (23: a write error), so the real fetch() is under test
    with open(os.path.join(m.bin, "curl"), "w", encoding="utf-8") as f:
        f.write("#!/bin/sh\n# a curl on a full disk: some bytes, then no more\n"
                "for a in \"$@\"; do [ \"$prev\" = -o ] && out=$a; prev=$a; done\n"
                "[ -z \"${out:-}\" ] || printf 'half a model' > \"$out\"\n"
                "echo 'curl: (23) Failure writing output to destination' >&2\n"
                "exit 23\n")
    os.chmod(os.path.join(m.bin, "curl"), 0o755)
    dest = os.path.join(m.models, "chaos.gguf.part")
    rc, out = m.sh("sh %s --fetch https://models.invalid/chaos.gguf %s %s"
                   % (os.path.join(REPO, "bootstrap.sh"), dest, "0" * 64))
    if rc == 0:
        return "the download exited 0 though curl failed"
    left = sorted(f for f in os.listdir(m.models) if f.endswith(".part"))
    if left:
        return "a partial file survived a failed download: %s" % ", ".join(left)
    m.note("bootstrap exits %d: %s" % (rc, _fit(" ".join(out.split()), 60)))
    m.note("no .part left in %s" % m.short(m.models))
    return ""


@scenario(heal=None, unhealed="two updates at once must not both move the "
                              "tree: the lock decides which one does")
def chaos_two_updates_at_once(m):
    """Two `spark update` at once: the second refuses in one signed line
    rather than racing the first through a checkout."""
    import fcntl
    from .update import UPDATE_LOCK
    path = os.path.join(m.state, os.path.basename(UPDATE_LOCK))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        rc, out = m.spark("update")
    finally:
        os.close(fd)
    if rc != 2:
        return "the second update exited %d, not 2 (a refusal): %r" % (rc, out.strip()[-200:])
    if "another spark update" not in out:
        return "the refusal does not say why: %r" % out.strip()[-200:]
    m.note("the second update refuses: %s" % _fit(" ".join(out.split()), 60))
    return ""


@scenario(heal=None, unhealed="two servers at once must not race for the "
                              "port: the lock decides which one starts")
def chaos_two_serves_at_once(m):
    """Two `spark serve on` at once: the second refuses instead of racing
    the first for the port."""
    import fcntl
    from . import LOCK_FILE
    m.brain.kill()              # nothing is serving: the start is real
    path = os.path.join(m.state, os.path.basename(LOCK_FILE))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        rc, out = m.spark("serve", "on")
    finally:
        os.close(fd)
    # 2, the same as the update lock: a gate refusal, not a world that
    # failed. Both locks answer the same situation, so both sign it alike
    if rc != 2:
        return "the second serve exited %d, not 2 (a refusal): %r" % (rc, out.strip()[-200:])
    if "another" not in out:
        return "the refusal does not say why: %r" % out.strip()[-300:]
    m.note("the second serve refuses (exit %d): %s"
           % (rc, _fit(" ".join(out.split()), 60)))
    return ""


@scenario(heal=None, mood="garbage",
          unhealed="a hostile answer is the model's, not the machine's: "
                   "the line keeps contract 4 and the widget runs nothing")
def chaos_hostile_line_answer(m):
    """A brain that answers prose, then nothing, then 40 kB with newlines
    in it: `spark line` still prints contract 4's two lines, every time."""
    kinds = []
    for nth in ("prose", "empty", "40 kB"):
        rc, out = m.spark("line", "--cwd", m.root, "--shell", "bash",
                          stdin="how big is this dir?\n")
        if "Traceback" in out:
            return "the %s answer ended in a traceback: %s" % (nth, out.strip()[-300:])
        if rc not in (0, 1):
            return "the %s answer exited %d (contract 4: 0 or 1)" % (nth, rc)
        lines = out.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        if len(lines) != 2:
            return "the %s answer printed %d lines, not 2: %r" % (nth, len(lines), out[:300])
        head = lines[0].split("\t")[0]
        if head not in ("cmd", "danger", "answer", "error"):
            return "the %s answer began %r, which contract 4 does not name" % (nth, head)
        if len(lines[0]) > 1200 or len(lines[1]) > ANSWER_MAX:
            return ("the %s answer came through at %d + %d characters: the "
                    "widget would wrap the prompt away" % (nth, len(lines[0]), len(lines[1])))
        kinds.append("%s -> %s" % (nth, head))
    m.note("contract 4 held: " + ", ".join(kinds))
    return ""


# ---------------------------------------------------------------- runner
def _command_of(remedy):
    """The runnable half of a remedy. Rows end a remedy with an aside --
    `spark serve off   (clears it)`, `spark update   (--fetch to ask origin)` --
    set off by two or more spaces. The aside is for the reader; the
    command is what runs, and the report prints exactly what ran."""
    return re.split(r"\s\s+\(", remedy, 1)[0].strip()


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
    if sc.row is None:
        # no row watches this one: what the break itself proved is the
        # whole rehearsal, and it says so rather than implying a row
        return True, m.notes + ["no row watches this: " + sc.unhealed]
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
        cmd, how = _command_of(remedy), "its own remedy"
    else:
        cmd, how = sc.heal, "the scenario's heal (the row's remedy is prose)"
    rc, out = m.sh(cmd)
    lines.append("heal, %s: %s" % (how, cmd))
    if rc != 0:
        return False, lines + ["the heal exited %d: %s" % (rc, out.strip()[-300:])]
    status, value, _r = m.row(sc.row)
    if status != sc.healed:
        return False, lines + ["healed, but %s is %s, not %s: %s"
                               % (sc.row, status, sc.healed, value)]
    lines.append("%s %s: %s" % (sc.row, status, value))
    return True, lines


def run(only=()):
    """Every scenario, each on its own throwaway machine. Exit 0 iff every
    one of them rehearsed."""
    say("%s check --chaos" % MARK)
    bad = ran = 0
    for sc in SCENARIOS:
        if only and sc.name not in only:
            continue
        ran += 1
        t0 = time.time()
        with tempfile.TemporaryDirectory(prefix="spark-chaos-") as tmp:
            root = os.path.join(tmp, sc.name)
            os.makedirs(root)
            brain = None
            try:
                brain = Brain(root, sc.mood)
                m = Machine(root, brain.url)
                m.brain = brain
                passed, lines = _judge(m, sc)
            except Exception as e:      # a crashed scenario is a failed one
                from . import log_exc
                log_exc("chaos " + sc.name)
                passed, lines = False, ["crashed: %s" % e]
            finally:
                if brain is not None:
                    brain.stop()
        bad += not passed
        say("  %s %-16s %s" % (GLYPH[OK] if passed else GLYPH[FAIL], sc.name,
                                _fit(sc.doc, 58 - len(" (%.1fs)" % 0)) + " (%.1fs)" % (time.time() - t0)))
        for line in lines:
            say("      %s %s" % (glyph("arrow"), line))
    if bad:
        say("  %d scenario%s did not rehearse" % (bad, "" if bad == 1 else "s"))
    else:
        # `ran`, not len(SCENARIOS): a filtered run must not claim the suite
        say("  every scenario rehearsed (%d)" % ran)
    return 1 if bad else 0
