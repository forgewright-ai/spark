#!/usr/bin/env python3
# spark tests/smoke.py -- the client against a stub llama-server, hermetic.
#
# A stdlib HTTP server on 127.0.0.1:<free port> plays llama-server: /health
# (200, or 503 while "loading"), /v1/models (bearer required), and
# /v1/chat/completions in both shapes -- JSON for `line`, SSE for the CLI.
# Every case runs bin/spark as a subprocess with a throwaway HOME and a
# scrubbed environment, exactly as a shell would.

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPARK = os.path.join(REPO, "bin", "spark")
TOKEN = "stub-token"
TIMINGS = {"prompt_n": 40, "prompt_per_second": 96.5, "predicted_n": 12, "predicted_per_second": 12.3, "cache_n": 30}
STATE = {"mode": "ok", "hits": 0}


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _auth(self):
        return self.headers.get("Authorization") == "Bearer " + TOKEN

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _sse(self, pieces):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for piece in pieces:
            self.wfile.write(("data: " + json.dumps({"choices": [{"delta": {"content": piece}}]}) + "\n\n").encode())
        self.wfile.write(("data: " + json.dumps({"choices": [{"delta": {}}], "timings": TIMINGS}) + "\n\n").encode())
        self.wfile.write(b"data: [DONE]\n\n")

    def do_GET(self):
        STATE["hits"] += 1
        if self.path == "/health":
            return self._send(503 if STATE["mode"] == "loading" else 200, {"status": "ok"})
        if self.path == "/v1/models":
            if not self._auth():
                return self._send(401, {"error": "unauthorized"})
            # the router's shape: one entry per role, aliased, with a
            # status; single_model plays a one-model machine (no ember)
            data = [{"id": "stub-7b-q4.gguf", "aliases": ["spark"], "status": {"value": "loaded"}},
                    {"id": "stub-ember-q4.gguf", "aliases": ["ember"], "status": {"value": "loaded"}}]
            return self._send(200, {"data": data[:1] if STATE.get("single_model") else data})
        self._send(404, {})

    def do_HEAD(self):
        # `spark model add`: a fake huggingface.co-shaped resolve URL. The
        # body is never sent (HEAD), but its would-be bytes and sha256
        # drive the headers, so a --sha256 test can plant a matching file.
        STATE["hits"] += 1
        m = re.match(r"^/org/repo/resolve/main/[^/?]+", self.path)
        if not m:
            self.send_response(404)
            self.end_headers()
            return
        body = STATE.get("head_body", b"x" * 4096)
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("x-linked-size", str(len(body)))
        self.send_header("x-linked-etag", '"%s"' % hashlib.sha256(body).hexdigest())
        self.end_headers()

    def do_POST(self):
        STATE["hits"] += 1
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        STATE["model"] = body.get("model")      # which role the request named
        if not self._auth():
            return self._send(401, {"error": "unauthorized"})
        if STATE["mode"] == "loading":
            return self._send(503, {"error": "loading model"})
        if STATE["mode"] == "garbage":
            return self._send(200, b"<html>not json</html>", "text/html")
        messages = body["messages"]
        user = messages[-1]["content"]
        if body.get("stream"):
            # `count` streams how many messages arrived, as the JSON shape does;
            # `wraptest` streams a long plain answer to prove the 80-col wrap
            if "count" in user:
                pieces = (str(len(messages)),)
            elif "wraptest" in user:
                pieces = tuple("word%02d " % i for i in range(1, 41))
            else:
                pieces = ("The ", "output ", "means ", "X.")
            return self._sse(pieces)
        self._send(200, {"choices": [{"message": {"content": json.dumps(answer_json(messages))}}], "timings": TIMINGS})


def is_do(messages):
    """mode do: the system message carries MODE_DO"""
    return "completing a task in steps" in messages[0]["content"]


def answer_json(messages):
    last = messages[-1].get("content", "")
    if "sameagain" in " ".join(m.get("content", "") for m in messages):
        if "already tried and failed" in last and "sameagain-fix" in " ".join(m.get("content", "") for m in messages):
            return {"kind": "cmd", "command": "echo FIXED", "hint": "a different way", "danger": False}
        return {"kind": "cmd", "command": "echo SAME", "hint": "same", "danger": False}
    user = messages[-1]["content"]
    if is_do(messages):
        goal = messages[1]["content"]           # the first user message is the goal
        if "forever" in goal:                   # never done: the step limit must stop it
            return {"kind": "cmd", "command": "echo again", "hint": "once more", "danger": False}
        if "badsum" in goal:                    # the done claims a number no output printed
            if "Output of" in user:
                return {"kind": "done", "command": "", "hint": "Total: 96 fields (sum of 21,5)", "danger": False}
            return {"kind": "cmd", "command": "echo 21; echo 5", "hint": "count things", "danger": False}
        if "goodsum" in goal:                   # the done claims the number the output printed
            if "Output of" in user:
                return {"kind": "done", "command": "", "hint": "Total: 26", "danger": False}
            return {"kind": "cmd", "command": "echo 26", "hint": "count things", "danger": False}
        if "missdo" in goal:                    # the step names a missing binary
            if "is not installed" in user:
                return {"kind": "done", "command": "", "hint": "gave up", "danger": False}
            return {"kind": "cmd", "command": "frobnicate --all", "hint": "scan things", "danger": False}
        if "Output of" in user or "STEP-ONE" in user or "skipped" in user:
            return {"kind": "done", "command": "", "hint": "all done", "danger": False}
        if "rm-plain" in goal:                  # unflagged by the model; the regex must
            return {"kind": "cmd", "command": "rm -rf ./junk", "hint": "delete junk", "danger": False}
        return {"kind": "cmd", "command": "echo STEP-ONE", "hint": "say hello", "danger": False}
    if "count" in user:           # how many messages arrived: system + history + user
        return {"kind": "answer", "command": "", "hint": str(len(messages)), "danger": False}
    if "delete" in user:
        return {"kind": "cmd", "command": "find . -name '*.tmp' -delete", "hint": "Delete every .tmp file below here", "danger": True}
    if "rm-plain" in user:      # the model forgets to flag it; the regex must
        return {"kind": "cmd", "command": "rm -rf build", "hint": "Remove the build directory", "danger": False}
    if "capital" in user:
        return {"kind": "answer", "command": "", "hint": "Paris", "danger": False}
    if "is not installed on this machine" in user:   # the head-word guard's retry
        if any("misscmd2" in m.get("content", "") for m in messages if m.get("role") == "user"):
            return {"kind": "cmd", "command": "frobnicate -h", "hint": "run frobnicate", "danger": False}
        return {"kind": "cmd", "command": "echo ok", "hint": "prints ok", "danger": False}
    if "misscmd" in user:
        return {"kind": "cmd", "command": "frobnicate -h", "hint": "run frobnicate", "danger": False}
    return {"kind": "cmd", "command": "find . -type f -size +1G -mtime -7", "hint": "Files over 1G changed this week", "danger": False}


def start_stub():
    srv = HTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d" % srv.server_address[1]


class T:
    def __init__(self):
        self.fail = 0

    def ok(self, cond, what, extra=""):
        print("  %s %s%s" % ("ok  " if cond else "FAIL", what, ("   " + extra) if extra and not cond else ""))
        if not cond:
            self.fail += 1


def main():
    srv, url = start_stub()
    t = T()
    with tempfile.TemporaryDirectory(prefix="spark-smoke-") as home:
        # GIT_* stripped too: a caller's GIT_DIR/GIT_INDEX_FILE (a pre-commit
        # hook, say) must never leak into a spawned `spark`, or its own git
        # calls (spark ver's credits line, the fork test below) run against
        # the caller's repo instead of the one spark was pointed at.
        env = {k: v for k, v in os.environ.items() if not k.startswith(("SPARK_", "XDG_", "SITE_", "GIT_"))}
        env.update({"HOME": home, "XDG_CONFIG_HOME": home + "/.config", "XDG_STATE_HOME": home + "/.local/state",
                    "XDG_DATA_HOME": home + "/.local/share", "SPARK_BASE_URL": url, "SPARK_API_KEY": TOKEN,
                    "SPARK_TIMEOUT": "5", "SPARK_NO_REFRESH": "1", "SHELL": "/bin/bash", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TERM": "xterm-256color"})
        os.makedirs(home + "/.config/spark")

        def spark(*args, stdin="", extra=None, exe=SPARK, cwd=None):
            e = dict(env)
            e.update(extra or {})
            p = subprocess.run([sys.executable, exe] + list(args), input=stdin, capture_output=True, text=True, env=e, timeout=30, cwd=cwd)
            return p.returncode, p.stdout, p.stderr

        print("smoke: stub llama-server at %s, HOME %s" % (url, home))

        # the line protocol
        rc, out, _ = spark("line", "--cwd", "/tmp", "--shell", "bash", stdin="? files bigger than 1G this week")
        lines = out.splitlines()
        t.ok(rc == 0 and lines[0] == "cmd\tfind . -type f -size +1G -mtime -7", "line: cmd", out)
        t.ok(len(lines) == 2 and lines[1] == "Files over 1G changed this week", "line: hint on line 2", out)
        t.ok(STATE.get("model") == "spark", "line: the request names the spark role", str(STATE.get("model")))
        rc, out, _ = spark("line", stdin="delete the tmp files?")
        t.ok(rc == 0 and out.startswith("danger\t"), "line: model-flagged danger", out)
        rc, out, _ = spark("line", stdin="rm-plain?")
        t.ok(rc == 0 and out.startswith("danger\trm -rf build"), "line: regex catches an unflagged rm -rf", out)
        rc, out, _ = spark("line", stdin="what is the capital of France?")
        t.ok(rc == 0 and out.splitlines() == ["answer", "Paris"], "line: answer", out)
        rc, out, _ = spark("line", stdin="?   ")
        t.ok(rc == 1 and out.startswith("error"), "line: empty question is an error", out)

        # the head-word guard: a command whose head word is not on this machine
        rc, out, _ = spark("line", stdin="? misscmd please")
        t.ok(rc == 0 and out.splitlines()[0] == "cmd\techo ok", "guard: a missing binary is re-asked once; the retry lands", out)
        rc, out, _ = spark("line", stdin="? misscmd2 please")
        lines = out.splitlines()
        t.ok(rc == 0 and lines[0] == "cmd\tfrobnicate -h" and lines[1].startswith("frobnicate: not on this machine -- "),
             "guard: a stubborn retry shows the original with the label", out)

        # ask / explain / the explain symlink
        rc, out, _ = spark("what", "does", "this", "mean")
        t.ok(rc == 0 and out.strip() == "* The output means X.", "ask: streamed answer", out)
        t.ok(STATE.get("model") == "ember", "ask: the request names the ember role", str(STATE.get("model")))
        rc, out, err = spark("explain", stdin="bash: foo: command not found\n")
        t.ok(rc == 0 and "means X" in out, "explain: reads stdin", out + err)
        t.ok(STATE.get("model") == "ember", "explain: the request names the ember role", str(STATE.get("model")))
        rc, out, err = spark("explain")
        t.ok(rc == 1 and "stdin" in err, "explain: refuses without stdin", err)
        rc, out, _ = spark(stdin="some output\n", exe=os.path.join(REPO, "bin", "explain"))
        t.ok(rc == 0 and "means X" in out, "explain symlink dispatches on its name", out)

        # last, brain, status, history
        rc, out, _ = spark("last")
        t.ok(rc == 0 and "[explain]" in out and "stub-ember-q4" in out, "last: an explain answered by the ember is recorded as the ember", out)
        rc, _, _ = spark("line", stdin="?biggest dir here", extra={"SPARK_TIMEOUT": "5"})
        rc, out, _ = spark("last")
        t.ok(rc == 0 and "stub-7b-q4" in out, "last: a line turn is recorded as the spark model", out)
        t.ok("12.3 tok/s (prompt 96 tok/s" in out, "last: shows the tokens per second the server reported", out)
        rc, out, _ = spark("stats", "--porcelain")
        t.ok(rc == 0 and "tg_mean\t12.3" in out and "cache_pct\t43" in out, "stats: mean tok/s and cache hits from the turns", out)
        rc, out, _ = spark("brain", "--porcelain")
        t.ok(rc == 0 and out.strip() == url + "\tstub-7b-q4\tmodel", "brain --porcelain: url, model, and that it is a raw model", out)
        turns = os.listdir(home + "/.local/state/spark/turns")
        t.ok(len(turns) == 1 and oct(os.stat(home + "/.local/state/spark/turns/" + turns[0]).st_mode & 0o777) == "0o600", "turns are 0600")
        t.ok(oct(os.stat(home + "/.local/state/spark").st_mode & 0o777) == "0o700", "state dir is 0700")
        rc, out, _ = spark("history", "clear")
        t.ok(rc == 0 and not os.listdir(home + "/.local/state/spark/turns"), "history clear", out)
        rc, out, _ = spark("line", stdin="anything?", extra={"SPARK_HISTORY": "off"})
        t.ok(rc == 0 and not os.listdir(home + "/.local/state/spark/turns"), "SPARK_HISTORY=off writes nothing")
        rc, out, _ = spark("status")
        t.ok(rc == 0 and out.startswith("spark") and "brain    " + url in out, "status", out)

        # off / on
        rc, out, _ = spark("off")
        t.ok(rc == 0 and os.path.exists(home + "/.local/state/spark/off"), "off creates the flag")
        rc, out, _ = spark("status")
        t.ok("off (spark on)" in out, "status says off", out)
        rc, out, _ = spark("on")
        t.ok(rc == 0 and not os.path.exists(home + "/.local/state/spark/off"), "on removes the flag")

        # grammar rule 4: the loop verbs answer -h first, signed (contract 8)
        for sub, first in (("last", "spark last -- the last exchange, with its tok/s"),
                           ("status", "spark status -- the full picture: brain, widget, service, soul, memory, last"),
                           ("brain", "spark brain -- what answers right now: a FORGE or a llama-server"),
                           ("off", "spark off -- silence the prompt widget, every pane at once"),
                           ("on", "spark on -- the prompt widget answers again"),
                           ("history", "spark history -- the threads kept on this machine"),
                           ("ver", "spark ver -- logo, version, credits")):
            rc, out, _ = spark(sub, "-h")
            t.ok(rc == 0 and out.splitlines()[0] == first, "spark %s -h signs (contract 8)" % sub, out)

        # SITE_QUIET_START=yes: bare spark is one line; spark status stays full
        rc, out, _ = spark(extra={"SITE_QUIET_START": "yes"})
        t.ok(rc == 0 and out.strip() == "spark -- ember stub-ember-q4 at %s (spark status for the rest)" % url,
             "SITE_QUIET_START=yes: bare spark answers with one line", out)
        rc, out, _ = spark("status", extra={"SITE_QUIET_START": "yes"})
        t.ok(rc == 0 and "brain    " in out, "spark status stays the full report under quiet start", out)

        # the brain cache is keyed on the candidates
        rc, out, _ = spark("brain", "--porcelain", extra={"SPARK_BASE_URL": "http://127.0.0.1:9"})
        t.ok(rc == 1 and out == "", "a different SPARK_BASE_URL is not answered from the cache", out)
        rc, out, _ = spark("brain", "--porcelain")
        t.ok(rc == 0, "the original brain is still cached", out)

        # failure shapes
        rc, out, _ = spark("line", stdin="x?", extra={"SPARK_API_KEY": "wrong"})
        t.ok(rc == 1 and out.startswith("error") and "token" in out, "401 -> error naming the token", out)
        STATE["mode"] = "loading"
        rc, out, _ = spark("line", stdin="x?", extra={"SPARK_TIMEOUT": "3"})
        t.ok(rc == 1 and "loading" in out, "503 -> loading", out)
        STATE["mode"] = "garbage"
        rc, out, _ = spark("line", stdin="x?")
        t.ok(rc == 1 and out.startswith("error"), "garbage -> error", out)
        STATE["mode"] = "ok"
        rc, out, _ = spark("line", stdin="x?", extra={"SPARK_BASE_URL": "http://127.0.0.1:9"})
        t.ok(rc == 1 and "no answer from SPARK_BASE_URL" in out, "down -> hint names the URL", out)

        rc, out, _ = spark("ver")
        t.ok(rc == 0 and re.search(r"^spark (\d+\.\d+(\+\d+)?|0\+[0-9a-f]+|dev)$", out, re.M)
             and re.search(r"by \S+ [·|] github\.com/\S+/\S+", out),
             "spark ver (the login greeting) still answers, credited", out)

        # a fork's credits line names its own remote (cli.credits(), from
        # `git remote get-url origin`), not the forgewright-ai literal.
        # The origin: a bare clone of this repo, with one commit on top of
        # HEAD carrying the working tree when it is dirty, so the fork
        # proves the tree at hand, not only what was last committed. That
        # commit is built entirely inside the *bare clone's* object store
        # (GIT_DIR=bare, GIT_WORK_TREE=REPO) -- no command here ever writes
        # into REPO's own .git, so a GIT_DIR/GIT_INDEX_FILE a caller (a
        # pre-commit hook, say) already has set for REPO cannot leak into a
        # write against REPO's real refs; every call also gets an explicit,
        # GIT_*-free base env, belt and braces.
        fork_t = tempfile.mkdtemp(prefix="spark-fork-")
        bare = os.path.join(fork_t, "origin.git")
        genv = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        subprocess.run(["git", "clone", "-q", "--bare", REPO, bare], env=genv, check=True, timeout=30)
        dirty = subprocess.run(["git", "-C", REPO, "status", "--porcelain"], env=genv,
                                capture_output=True, text=True, timeout=10).stdout
        if dirty.strip():
            wenv = dict(genv, GIT_DIR=bare, GIT_WORK_TREE=REPO, GIT_INDEX_FILE=os.path.join(fork_t, "index"))
            subprocess.run(["git", "add", "-A"], env=wenv, check=True, timeout=30)
            tree = subprocess.run(["git", "write-tree"], env=wenv, capture_output=True,
                                   text=True, check=True, timeout=10).stdout.strip()
            branch = subprocess.run(["git", "-C", bare, "symbolic-ref", "--short", "HEAD"], env=genv,
                                     capture_output=True, text=True, check=True, timeout=10).stdout.strip()
            # an unborn branch (an orphan checkout before its first commit) has
            # no parent: the fork's first commit is the working tree itself
            par = subprocess.run(["git", "-C", bare, "rev-parse", "--verify", "-q", branch], env=genv,
                                 capture_output=True, text=True, timeout=10)
            parents = ["-p", par.stdout.strip()] if par.returncode == 0 and par.stdout.strip() else []
            commit = subprocess.run(["git", "commit-tree", tree] + parents + ["-m", "smoke: the working tree"],
                                     env=dict(genv, GIT_DIR=bare), capture_output=True, text=True,
                                     check=True, timeout=10).stdout.strip()
            subprocess.run(["git", "-C", bare, "update-ref", "refs/heads/smoke-test", commit],
                            env=genv, check=True, timeout=10)
            subprocess.run(["git", "-C", bare, "symbolic-ref", "HEAD", "refs/heads/smoke-test"],
                            env=genv, check=True, timeout=10)
        fork = os.path.join(fork_t, "fork")
        subprocess.run(["git", "clone", "-q", bare, fork], env=genv, check=True, timeout=30)
        subprocess.run(["git", "-C", fork, "remote", "set-url", "origin", "https://github.com/someone/sparkfork.git"],
                        env=genv, check=True, timeout=10)
        rc, out, _ = spark("ver", exe=os.path.join(fork, "bin", "spark"))
        t.ok(rc == 0 and "by someone" in out and "github.com/someone/sparkfork" in out,
             "a fork's origin remote names itself in spark ver's credits line", out)

        # a lone word is a slip, not a question
        rc, out, _ = spark("gruvbox-dark")
        t.ok(rc == 2 and "spark theme gruvbox-dark" in out, "a palette name alone points at spark theme", out)
        rc, out, _ = spark("qwen3-8b")
        t.ok(rc == 2 and "spark model qwen3-8b" in out, "a model name alone points at spark model", out)
        rc, out, _ = spark("frobnicate")
        t.ok(rc == 2 and "no command named" in out, "an unknown word alone is refused, not asked", out)
        rc, out, _ = spark("frobnicate?")
        t.ok(rc == 0 and out.startswith("* "), "one word ending in ? is still a question, marked", out)
        rc, out, _ = spark("quite", "start", "on")
        t.ok(rc == 2 and "try: spark quiet" in out, "a misspelled verb with arguments is a typo, not a question", out)
        rc, out, _ = spark("quiett")
        t.ok(rc == 2 and "try: spark quiet" in out, "a misspelled verb alone points at the right spelling", out)

        # config hygiene
        with open(home + "/.config/spark/spark.env", "w") as f:
            f.write("SPARK_PORT=8080\nSPARK_MODEL=$(rm -rf /)\n")
        rc, out, err = spark("brain", "--porcelain")
        t.ok(rc == 2 and "spark.env:2" in err, "shell syntax in spark.env refused with the line number", err)
        os.remove(home + "/.config/spark/spark.env")

        # threads: `?` starts one, `??` goes on with it (the stub counts the messages)
        threads = home + "/.local/state/spark/threads"
        spark("history", "clear")
        rc, out, _ = spark("line", stdin="? a")
        rc, out, _ = spark("line", stdin="?? count")
        t.ok(rc == 0 and out.splitlines() == ["answer", "4"], "?? sends system + the 2 earlier messages + the line", out)
        rc, out, _ = spark("line", stdin="? count")
        t.ok(rc == 0 and out.splitlines() == ["answer", "2"], "? starts afresh: system + the line", out)
        names = sorted(os.listdir(threads))
        t.ok(len(names) == 2 and all(oct(os.stat(threads + "/" + n).st_mode & 0o777) == "0o600" for n in names), "thread files are 0600", names)
        t.ok(oct(os.stat(threads).st_mode & 0o777) == "0o700", "threads dir is 0700")
        rc, out, _ = spark("history")
        t.ok(rc == 0 and "2 turns  a" in out and "1 turn  count" in out, "history lists the threads with their turns and title", out)
        rc, out, _ = spark("last")
        t.ok(rc == 0 and "thread " + names[-1][:-6] in out, "last names the thread of the turn", out)
        rc, out, _ = spark("history", "clear")
        t.ok(rc == 0 and "2 threads" in out and not os.listdir(threads), "history clear empties the threads too", out)
        rc, out, _ = spark("line", stdin="?? count", extra={"SPARK_HISTORY": "off"})
        t.ok(rc == 0 and out.splitlines() == ["answer", "2"] and not os.listdir(threads), "SPARK_HISTORY=off: ?? is ?, and no thread is written", out)
        rc, out, _ = spark("what", "does", "count", "mean")
        t.ok(rc == 0 and len(os.listdir(threads)) == 1, "spark <words> starts a thread of its own", out)
        spark("history", "clear")

        # chat: one turn goes on with the newest thread; the REPL reads stdin
        spark("line", stdin="? a")
        rc, out, _ = spark("chat", "count")
        t.ok(rc == 0 and out.strip() == "* 4", "spark chat <words> continues the newest thread, marked (system + 2 + line)", out)
        t.ok(STATE.get("model") == "ember", "chat: the request names the ember role", str(STATE.get("model")))
        rc, out, _ = spark("chat", stdin="count\n\n/new\ncount\n")
        answers = re.findall(r"chat> \* (\d+)", out)
        t.ok(rc == 0 and answers == ["6", "2"], "spark chat REPL: continues (6), /new starts afresh (2), blank ignored", out)
        t.ok(out.count("chat> ") == 5 and "fresh thread" in out, "the REPL prompts, says so on /new, ends on EOF", out)
        t.ok(out.count("chat -- /help, Ctrl-D or /q ends") == 1, "the intro line prints once", out)
        t.ok("* " in out, "chat replies print marked answers", out)
        t.ok(len(os.listdir(threads)) == 2, "the REPL left one thread continued and one new")
        rc, out, _ = spark("chat", "-h")
        t.ok(rc == 0 and out.splitlines()[0] == "spark chat -- a conversation", "spark chat -h signs (contract 8)", out)
        rc, out, _ = spark("talk", "count")
        t.ok(rc == 2 and out.strip() == "spark talk -- gone: spark chat",
             "spark talk is gone: one line naming spark chat, exit 2, no model call", out)
        # the quit grammar: all silent, rc 0, nothing sent to the model
        hits0 = STATE["hits"]
        rc, out, err = spark("chat", stdin=":q\n")
        t.ok(rc == 0 and out == "chat -- /help, Ctrl-D or /q ends\nchat> " and err == "" and STATE["hits"] == hits0,
             "chat: :q quits silently, no model call (the role-played-Exited trap)", repr(out))
        rc, out, err = spark("chat", stdin="exit\n")
        t.ok(rc == 0 and out.endswith("chat> ") and err == "" and STATE["hits"] == hits0, "chat: exit quits silently too", repr(out))
        rc, out, err = spark("chat", stdin="\n\n:q\n")
        t.ok(rc == 0 and out.count("chat> ") == 3 and STATE["hits"] == hits0, "chat: blank lines ignored, no model call", repr(out))
        rc, out, _ = spark("chat", "count", extra={"SPARK_HISTORY": "off"})
        t.ok(rc == 0 and out.strip() == "* 2", "SPARK_HISTORY=off: chat has nothing to go on with", out)
        spark("history", "clear")

        # /help: five lines, one per verb, no model call
        hits0 = STATE["hits"]
        rc, out, err = spark("chat", stdin="/help\n:q\n")
        t.ok(rc == 0 and STATE["hits"] == hits0, "chat: /help hits the stub zero times", out + err)
        for v in ("/help", "/new", "/resume", "/clear", "/last", "/model", "/q"):
            t.ok(v in out, "chat: /help lists %s" % v, out)

        # an unknown slash verb is refused on stderr, not sent to the model
        hits0 = STATE["hits"]
        rc, out, err = spark("chat", stdin="/nope\n:q\n")
        t.ok(rc == 0 and STATE["hits"] == hits0 and "no /nope -- /help lists them" in err,
             "chat: an unknown /nope is refused on stderr, no model call", out + err)

        # /last: the last turn, with its tok/s
        rc, out, err = spark("chat", stdin="hello there\n/last\n:q\n")
        t.ok(rc == 0 and "tok/s" in out, "chat: /last shows the last turn, with its tok/s", out)
        spark("history", "clear")

        # /model: names the stub's ember (see the stub's /v1/models fixture)
        rc, out, err = spark("chat", stdin="/model\n:q\n")
        t.ok(rc == 0 and ("ember: stub-ember-q4 via " + url) in out, "chat: /model names the stub's ember", out)

        # /model on a one-model machine: no ember is served, so no ember
        # label -- the single model answers everything
        STATE["single_model"] = True
        rc, out, err = spark("chat", stdin="/model\n:q\n")
        t.ok(rc == 0 and ("model: stub-7b-q4 via " + url) in out and "ember:" not in out,
             "chat: /model with one model served says model:, never ember:", out + err)
        STATE["single_model"] = False

        # /resume and --thread: picking up an older thread. Two seeded
        # threads: "older" gets 2 turns, "newer" 1 -- the stub's `count`
        # answer (system + history + line) proves which history was sent.
        spark("history", "clear")
        spark("line", stdin="? older")
        spark("line", stdin="?? more")            # the older thread: 2 turns
        spark("line", stdin="? newer")            # the newer thread: 1 turn
        hits0 = STATE["hits"]
        rc, out, err = spark("chat", stdin="/resume\n:q\n")
        t.ok(rc == 0 and "1) 1 turn  newer" in out and "2) 2 turns  older" in out and STATE["hits"] == hits0,
             "chat: /resume lists the newest threads, numbered, no model call", out + err)
        rc, out, err = spark("chat", stdin="/resume 9\n:q\n")
        t.ok(rc == 0 and STATE["hits"] == hits0 and "no thread 9 -- /resume lists them" in err,
             "chat: /resume with an unknown N is refused on stderr", out + err)
        rc, out, err = spark("chat", stdin="/resume 2\ncount\n")
        t.ok(rc == 0 and "* resuming: older (2 turns)" in out and re.findall(r"chat> \* (\d+)", out) == ["6"],
             "chat: /resume 2 goes on with the older thread (system + 4 + line)", out + err)
        rc, out, err = spark("chat", stdin="/resume\n:q\n", extra={"SPARK_HISTORY": "off"})
        t.ok(rc == 0 and "spark: history is off" in err, "chat: /resume with history off says so", out + err)
        rc, out, _ = spark("chat", "--thread", "1", "count")
        t.ok(rc == 0 and out.strip() == "* 8", "spark chat --thread 1 count goes on with the newest thread", out)
        rc, out, _ = spark("chat", "--thread", "9", "count")
        t.ok(rc == 2 and out.strip() == "spark chat -- no thread 9 (spark history lists them)",
             "chat --thread with an unknown N refuses, signed, exit 2", out)
        rc, out, _ = spark("chat", "--thread", "1", "count", extra={"SPARK_HISTORY": "off"})
        t.ok(rc == 2 and out.strip() == "spark chat -- history is off (SPARK_HISTORY)",
             "chat --thread with history off refuses, signed, exit 2", out)

        # /clear piped: a silent no-op -- no escapes on stdout, the thread lives
        rc, out, err = spark("chat", stdin="count\n/clear\ncount\n")
        answers = [int(n) for n in re.findall(r"chat> \* (\d+)", out)]
        t.ok(rc == 0 and "\033[" not in out and len(answers) == 2 and answers[1] == answers[0] + 2,
             "chat: /clear piped prints no escapes and the thread goes on", repr(out))
        spark("history", "clear")

        # wrap at 80 columns when piped: a long canned answer breaks into
        # short lines (the leading `chat> ` of the first one is not part of
        # the wrap and is stripped before measuring)
        rc, out, _ = spark("chat", stdin="wraptest\n:q\n")
        lines = [l[len("chat> "):] if l.startswith("chat> ") else l for l in out.splitlines()]
        t.ok(rc == 0 and all(len(l) <= 79 for l in lines), "chat: wraps at 80 columns when piped", out)
        t.ok(len([l for l in lines if l.strip()]) > 2, "chat: the long answer actually wrapped onto several lines", out)
        spark("history", "clear")

        # SPARK_HISTORY=off: no chat-history file (piped stdin is never a
        # tty regardless, so this only proves the file stays absent here;
        # the readline-at-a-tty path is proven by hand, see the wave report)
        rc, out, _ = spark("chat", stdin="hello\n:q\n", extra={"SPARK_HISTORY": "off"})
        t.ok(rc == 0 and not os.path.exists(home + "/.local/state/spark/chat-history"),
             "SPARK_HISTORY=off: no chat-history file written", out)
        spark("history", "clear")

        # @FILE: the text rides along, as typed; refusals
        work = tempfile.mkdtemp(prefix="spark-work-")
        with open(work + "/f.txt", "w") as f:
            f.write("SECRET-MARK line one\n")
        with open(home + "/f2.txt", "w") as f:
            f.write("HOME-MARK\n")
        with open(work + "/big.txt", "w") as f:
            f.write("x" * 40000)
        with open(work + "/bin.dat", "wb") as f:
            f.write(b"abc\0def")
        os.mkdir(work + "/dir")
        rc, out, _ = spark("@f.txt", "count", cwd=work)
        t.ok(rc == 0 and out.strip() == "* 2", "spark @FILE words asks, streamed", out)
        rc, out, _ = spark("@f.txt", cwd=work)
        t.ok(rc == 0 and out.startswith("* "), "spark @FILE alone asks for a summary", out)
        rc, out, err = spark("@missing.txt", "x", cwd=work)
        t.ok(rc == 1 and "no such file" in err, "@missing -> no such file", err)
        rc, out, err = spark("@dir", "x", cwd=work)
        t.ok(rc == 1 and "is a directory" in err, "@dir -> refused with a hint", err)
        rc, out, err = spark("@bin.dat", "x", cwd=work)
        t.ok(rc == 1 and "not a text file" in err, "a NUL byte -> not a text file", err)
        spark("history", "clear")
        rc, out, err = spark("chat", stdin="@nope.txt x\ncount\n", cwd=work)
        t.ok(rc == 0 and "no such file" in err and re.findall(r"chat> \* (\d+)", out) == ["2"], "the REPL refuses a bad @FILE and goes on", out + err)
        spark("history", "clear")

        # soul: built-in until edited; the editor's file is private
        rc, out, _ = spark("soul")
        t.ok(rc == 0 and out.startswith("soul  builtin") and "You are spark" in out, "spark soul: built-in paragraph", out)
        rc, out, _ = spark("soul", "edit", extra={"EDITOR": "true"})
        soulf = home + "/.config/spark/soul"
        t.ok(rc == 0 and os.path.isfile(soulf) and oct(os.stat(soulf).st_mode & 0o777) == "0o600", "spark soul edit seeds a 0600 file", out)
        rc, out, _ = spark("soul")
        t.ok(rc == 0 and out.startswith("soul  file"), "spark soul: now from the file", out)
        with open(soulf, "w") as f:
            f.write("Call yourself Fixture.\n")

        # memory: remember, list, forget; refusals
        rc, out, _ = spark("remember", "the", "box", "is", "called", "forge")
        t.ok(rc == 0 and "remembered" in out, "spark remember", out)
        rc, out, _ = spark("memory")
        t.ok(rc == 0 and "  1   the box is called forge" in out, "spark memory lists the fact, numbered", out)
        rc, out, _ = spark("remember", "the", "box", "is", "called", "forge")
        t.ok(rc == 1 and "already" in out, "a duplicate fact is refused", out)
        rc, out, _ = spark("forget", "nope")
        t.ok(rc == 1, "forget of an unknown fact is refused", out)
        rc, out, err = spark("memory", extra={"SPARK_MEMORY": "maybe"})
        t.ok(rc == 2 and "SPARK_MEMORY" in err, "SPARK_MEMORY=maybe is refused by name", err)
        rc, out, _ = spark("status")
        t.ok(rc == 0 and "  soul     yours, " in out and "  memory   1 fact" in out and " threads" in out, "status shows soul, memory, threads", out)

        # the privacy claim: what the request contains
        req = {}

        class Peek(Stub):
            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                req["body"] = json.loads(self.rfile.read(n))
                if req["body"].get("stream"):
                    return self._sse(("ok",))
                reply = answer_json(req["body"]["messages"]) if is_do(req["body"]["messages"]) else {"kind": "answer", "command": "", "hint": "ok", "danger": False}
                self._send(200, {"choices": [{"message": {"content": json.dumps(reply)}}]})
        srv2 = HTTPServer(("127.0.0.1", 0), Peek)
        threading.Thread(target=srv2.serve_forever, daemon=True).start()
        url2 = "http://127.0.0.1:%d" % srv2.server_address[1]
        spark("line", "--cwd", "/some/dir", "--shell", "zsh", stdin="hello?", extra={"SPARK_BASE_URL": url2})
        sent = json.dumps(req.get("body", {}))
        t.ok("[cwd /some/dir]" in sent and "hello?" in sent and "zsh" in sent, "request carries cwd, line, shell", sent[:200])
        t.ok(home not in sent and "HOME" not in sent, "request carries no HOME path or environment", sent[:200])
        msgs = req.get("body", {}).get("messages", [])
        system1 = msgs[0]["content"] if msgs else ""
        t.ok(req.get("body", {}).get("model") == "spark", "the prompt line names the spark role", sent[:200])
        t.ok("Call yourself Fixture." not in sent and "the box is called forge" not in sent,
             "the line carries no soul and no fact (the identity is the ember's)", system1[:200])
        spark("line", "--cwd", "/some/dir", "--shell", "zsh", stdin="hello again?", extra={"SPARK_BASE_URL": url2})
        sent = json.dumps(req.get("body", {}))
        t.ok(home not in sent, "the second request carries no HOME path either")
        t.ok(req["body"]["messages"][0]["content"] == system1, "the system message is byte-identical across requests (prompt cache)")
        spark("tell", "me", "something", extra={"SPARK_BASE_URL": url2})
        sent = json.dumps(req.get("body", {}))
        msgs = req.get("body", {}).get("messages", [])
        esys = msgs[0]["content"] if msgs else ""
        t.ok(req.get("body", {}).get("model") == "ember", "a sentence names the ember role", sent[:200])
        t.ok("Call yourself Fixture." in esys and "Call yourself" not in msgs[-1]["content"], "the soul goes in the ember's system message only", esys[:200])
        t.ok("the box is called forge" in esys and "remembered" in esys, "the remembered fact goes in the ember's system message", esys[:200])
        t.ok(home not in sent, "the ember request carries no HOME path either")
        t.ok("Flags that exist" in esys and "Preferred when installed" in esys, "ask keeps the full shell prefix", esys[:200])
        t.ok("spark's own commands" in esys and "spark quiet start|login|boot on|off" in esys,
             "ask knows spark's own commands (the machine can explain itself)", esys[:200])
        t.ok("spark's own commands" in system1, "the line prompt knows spark's own commands too", system1[:200])
        # chat sheds the shell costume: one machine line + identity + the mode
        spark("chat", "hello", extra={"SPARK_BASE_URL": url2})
        csys = req["body"]["messages"][0]["content"]
        t.ok(req["body"].get("model") == "ember", "chat names the ember role", csys[:100])
        t.ok(csys.startswith("You are on ") and "Call yourself Fixture." in csys and "This is a conversation" in csys,
             "chat: one machine line + identity + the chat mode", csys[:200])
        t.ok("Preferred when installed" not in csys and "Flags that exist" not in csys and "Package manager" not in csys
             and "System tools" not in csys, "chat sheds the shell costume", csys[:200])
        t.ok("spark's own commands" in csys and "The look: spark theme NAME" in csys,
             "chat knows spark's own commands, grouped with meanings", csys[:200])
        spark("chat", "hello again", extra={"SPARK_BASE_URL": url2})
        t.ok(req["body"]["messages"][0]["content"] == csys, "the chat system message is byte-identical across requests")
        spark("tell", "me", "again", extra={"SPARK_BASE_URL": url2, "SPARK_MEMORY": "off"})
        sent = json.dumps(req.get("body", {}))
        t.ok("remembered" not in req["body"]["messages"][0]["content"] and home not in sent, "SPARK_MEMORY=off sends no facts", sent[:200])
        rc, out, _ = spark("forget", "1")
        t.ok(rc == 0 and "forgot" in out, "spark forget 1", out)
        rc, out, _ = spark("memory")
        t.ok(rc == 0 and "  1   " not in out and "0 facts" in out, "the listing is empty again", out)
        # the user chose none: a stray .gguf is not a choice, the peer is the story
        stray = home + "/.local/share/spark/models"
        os.makedirs(stray, exist_ok=True)
        open(stray + "/stray-model.gguf", "w").write("x")
        e2 = {k: v for k, v in env.items() if k != "SPARK_BASE_URL"}
        e2["SITE_PEER_AI_URL"] = "http://127.0.0.1:9"
        p2 = subprocess.run([sys.executable, SPARK, "status"], capture_output=True, text=True, env=e2, timeout=30)
        t.ok("stray-model" not in p2.stdout and "no answer from the peer http://127.0.0.1:9" in p2.stdout,
             "model none + dead peer: the hint names the peer, not the stray file", p2.stdout)
        os.remove(stray + "/stray-model.gguf")
        rc, out, _ = spark("bar", extra={"SITE_SHELL": "on"})       # a status-right runs with the layer on
        t.ok(rc == 0 and "load " in out and "spark bar" not in out,
             "bare spark bar without a tty draws the line (a status-right cannot toggle itself off)", out)
        # ver: the login greeting. The version line comes from git describe
        # (lib/spark/version.py); recomputed here as its own subprocess
        # against REPO, never by importing spark.version into this process
        # -- the real cache file (state/version), if any, must stay
        # untouched. The logo stays bare of escapes when piped; nothing on
        # stderr, ever.
        gd = subprocess.run(["git", "-C", REPO, "describe", "--tags", "--abbrev=7"], capture_output=True, text=True, timeout=5)
        tag = gd.stdout.strip()
        m = re.match(r"^v(\d+\.\d+)(?:-(\d+)-g[0-9a-f]+)?$", tag) if gd.returncode == 0 and tag else None
        if m:
            version = m.group(1) + ("+" + m.group(2) if m.group(2) else "")
        else:
            rp = subprocess.run(["git", "-C", REPO, "rev-parse", "--short=7", "HEAD"], capture_output=True, text=True, timeout=5)
            sha = rp.stdout.strip()
            version = ("0+" + sha) if rp.returncode == 0 and sha else "dev"   # dev: a branch with no commit yet
        rc, out, err = spark("ver")
        t.ok(rc == 0 and err == "" and re.search(r"^spark %s$" % re.escape(version), out, re.M),
             "ver: the version line matches git describe", out + err)
        t.ok("\u2588" in out and "\033" not in out and "\\033" not in out, "ver: the logo is drawn, without escapes, when piped", out)
        t.ok("CREDITS.md" in out, "ver: names CREDITS.md for the rest of the licenses", out)
        rc, out, _ = spark("remember", "-h")
        t.ok(rc == 0 and out.startswith("spark memory -- "), "remember -h is help, not a fact", out)
        rc, out, _ = spark("forget", "-h")
        t.ok(rc == 0 and out.startswith("spark memory -- "), "forget -h is help", out)
        # the repair guard: a ?? turn never re-serves the failed command
        rc, out, _ = spark("line", stdin="? sameagain-fix please")
        rc, out, _ = spark("line", stdin="?? it printed nothing")
        t.ok(rc == 0 and out.splitlines()[0] == "cmd\techo FIXED", "?? re-asks and a new command lands", out)
        rc, out, _ = spark("line", stdin="? sameagain-stub please")
        rc, out, _ = spark("line", stdin="?? still nothing")
        t.ok(rc == 0 and "already tried above" in out, "a stubborn repeat is labeled, not re-served as new", out)
        rc, out, _ = spark("memory")
        t.ok("0 facts" in out, "no fact named -h was kept", out)

        # @FILE: what of the file leaves, and under which name
        spark("@f.txt", "why", cwd=work, extra={"SPARK_BASE_URL": url2})
        sent = json.dumps(req.get("body", {}))
        user_msg = req["body"]["messages"][-1]["content"]
        t.ok("File f.txt:\nSECRET-MARK" in user_msg and user_msg.endswith("line one\n") and "why" in user_msg, "the file's text goes in the user message under its name", user_msg[:200])
        t.ok("Output:" not in user_msg, "a file is not labelled as output", user_msg[:200])
        t.ok(home not in sent and work + "/f.txt" not in sent, "only the name as typed leaves, never the absolute path", sent[:200])
        spark("@~/f2.txt", "why", cwd=work, extra={"SPARK_BASE_URL": url2})
        sent = json.dumps(req.get("body", {}))
        user_msg = req["body"]["messages"][-1]["content"]
        t.ok("File ~/f2.txt:\nHOME-MARK" in user_msg and home not in sent, "@~/FILE expands ~ but sends the tilde", user_msg[:200])
        spark("@big.txt", "why", cwd=work, extra={"SPARK_BASE_URL": url2})
        user_msg = req["body"]["messages"][-1]["content"]
        t.ok("[... 24000 chars cut ...]" in user_msg and len(user_msg) < 16200, "a 40 kB file goes as head 4 kB + cut + tail 12 kB", user_msg[3990:4050])
        spark("@f.txt", "why", stdin="err: boom\n", cwd=work, extra={"SPARK_BASE_URL": url2})
        user_msg = req["body"]["messages"][-1]["content"]
        t.ok(user_msg.index("Output:\nerr: boom") < user_msg.index("File f.txt:"), "piped output comes first, then the files", user_msg[:200])
        rc, out, _ = spark("last")
        t.ok(rc == 0 and "@f.txt why" in out, "last shows the @FILE turn as typed", out)

        # spark do: one confirmed command at a time (SPARK_DO_STDIN=1 reads the confirmations from stdin)
        hook = {"SPARK_DO_STDIN": "1"}
        spark("history", "clear")
        rc, out, err = spark("do", "say", "hello", stdin="\n", extra=hook, cwd=work)
        t.ok(rc == 0 and "STEP-ONE" in out and "done  all done" in out, "spark do: proposes, Enter runs it, the output ends it", out + err)
        t.ok("1  echo STEP-ONE   say hello" in out and "Enter runs it" in out, "spark do: the step line and the prompt", out)
        names = os.listdir(threads)
        lines = [json.loads(l) for l in open(threads + "/" + names[0]) if l.strip()] if len(names) == 1 else []
        t.ok(len(lines) == 4 and [l["role"] for l in lines] == ["user", "assistant"] * 2 and "Output of `echo STEP-ONE` (exit 0)" in lines[2]["text"], "spark do: one thread, goal / step / output / done", lines)
        turns = [json.loads(l) for f in os.listdir(home + "/.local/state/spark/turns") for l in open(home + "/.local/state/spark/turns/" + f) if l.strip()]
        dos = [x for x in turns if x.get("mode") == "do"]
        t.ok(len(dos) == 2 and dos[0]["kind"] == "cmd" and dos[0]["rc"] == 0 and dos[0]["command"] == "echo STEP-ONE" and dos[1]["kind"] == "done", "spark do: the turn log has the step with its rc, then the done", dos)
        os.mkdir(work + "/junk")
        rc, out, err = spark("do", "rm-plain", "junk", stdin="no\n", extra=hook, cwd=work)
        t.ok(rc == 0 and "type yes to run it" in out and os.path.isdir(work + "/junk"), "spark do: an unflagged rm -rf asks for yes; `no` does not run it", out + err)
        t.ok(out.splitlines()[1].startswith("! 1  rm -rf ./junk"), "spark do: the danger mark on the step line", out)
        rc, out, err = spark("do", "rm-plain", "junk", stdin="yes\n", extra=hook, cwd=work)
        t.ok(rc == 0 and not os.path.exists(work + "/junk"), "spark do: `yes` runs it", out + err)
        rc, out, err = spark("do", "forever", stdin="\n" * 9, extra=hook, cwd=work)
        t.ok(rc == 1 and "step limit (8)" in out and out.count("again\n") == 8, "spark do: stops after 8 steps", out + err)
        rc, out, err = spark("do", "forever", stdin="q\n", extra=hook, cwd=work)
        t.ok(rc == 0 and "stopped after 0 steps" in out and "again\n" not in out, "spark do: q quits before running", out + err)
        rc, out, err = spark("do", "forever", stdin="e\necho EDITED\nq\n", extra=hook, cwd=work)
        t.ok(rc == 0 and "EDITED" in out and "stopped after 1 step" in out, "spark do: e edits the command, then it runs", out + err)
        rc, out, err = spark("do", "forever", stdin="s\nq\n", extra=dict(hook, SPARK_BASE_URL=url2), cwd=work)
        t.ok(rc == 0 and "skipped" in req["body"]["messages"][-1]["content"], "spark do: s tells the model the step was skipped", out + err)
        t.ok(req["body"].get("model") == "ember", "spark do proposes with the ember role", str(req["body"].get("model")))
        rc, out, err = spark("do", "say", "hello", stdin="\n", cwd=work)
        t.ok(rc == 1 and "terminal" in err, "spark do: without a terminal it refuses", err)
        rc, out, _ = spark("do", "-h")
        t.ok(rc == 0 and out.splitlines()[0] == "spark do -- a task, step by step", "spark do -h signs (contract 8)", out)
        rc, out, _ = spark("do")
        t.ok(rc == 2 and out.startswith("spark do --"), "spark do alone: usage, exit 2", out)
        before = len(os.listdir(threads))
        rc, out, err = spark("do", "say", "hello", stdin="\n", extra=dict(hook, SPARK_HISTORY="off"), cwd=work)
        t.ok(rc == 0 and "done  all done" in out and len(os.listdir(threads)) <= before, "SPARK_HISTORY=off: spark do still reads its own steps, keeps no thread", out + err)
        # the provenance guard and the driver line
        rc, bout, _ = spark("brain", "--porcelain")
        fam = bout.strip().split("\t")[1].split("-")[0]
        rc, out, err = spark("do", "badsum", "inventory", stdin="\n", extra=hook, cwd=work)
        t.ok(rc == 0 and "! done  Total: 96 fields" in out and "unchecked: no command produced 96" in out,
             "spark do: a done number no output backs is marked unchecked", out + err)
        t.ok(("driving with " + fam) in out.splitlines()[0], "spark do: opens naming the model driving", out)
        rc, out, err = spark("do", "goodsum", stdin="\n", extra=hook, cwd=work)
        t.ok(rc == 0 and "unchecked" not in out and "done  Total: 26" in out, "spark do: a number an output backs passes clean", out + err)
        # the head-word guard in do: never offered, fed back, the loop goes on
        rc, out, err = spark("do", "missdo", "scan", stdin="", extra=hook, cwd=work)
        t.ok(rc == 0 and "frobnicate: not on this machine" in out and "gave up" in out and "Enter runs it" not in out,
             "spark do: a step naming a missing binary is not offered to run", out + err)
        rc, out, err = spark("do", "missdo", "scan", stdin="", extra=dict(hook, SPARK_BASE_URL=url2), cwd=work)
        t.ok(rc == 0 and "frobnicate is not installed on this machine" in req["body"]["messages"][-1]["content"],
             "spark do: the model hears the missing binary as feedback", req["body"]["messages"][-1]["content"][:120])
        # the ember verb: status, choose, refuse, the shared table's marks
        mem = {"SPARK_NO_APPLY": "1", "SPARK_MEM_TOTAL_GB": "64"}
        rc, out, _ = spark("ember", extra=mem)
        t.ok(rc == 0 and re.search(r"^  spark", out, re.M) and re.search(r"^  ember", out, re.M),
             "spark ember: one line per role", out)
        rc, out, _ = spark("ember", "-h")
        t.ok(rc == 0 and out.splitlines()[0] == "spark ember -- the conversational model",
             "spark ember -h signs (contract 8)", out)
        rc, out, _ = spark("ember", "nosuch", extra=mem)
        t.ok(rc == 2 and "spark ember list" in out, "an unknown ember name is refused, naming the list", out)
        rc, out, _ = spark("ember", "none", extra=mem)
        t.ok(rc == 0 and "SITE_EMBER_MODEL=none" in out, "spark ember none writes the key", out)
        # the restart narration lives behind apply(); SPARK_NO_APPLY returns
        # before it (same as spark model), so none of it may leak here
        t.ok("restarting" not in out and "download" not in out,
             "SPARK_NO_APPLY: the key only -- no restart or download narration", out)
        t.ok("SITE_EMBER_MODEL=none" in open(home + "/.config/spark/site.env").read(), "site.env carries the choice")
        rc, out, _ = spark("ember", extra=mem)
        t.ok(rc == 0 and "spark answers everything" in out, "ember none: spark answers everything", out)
        marks = {"SPARK_NO_APPLY": "1", "SPARK_MEM_TOTAL_GB": "64",
                 "SITE_AI_MODEL": "qwen3-1-7b", "SITE_EMBER_MODEL": "qwen3-4b"}
        rc, out, _ = spark("model", "list", extra=marks)
        t.ok(rc == 0 and re.search(r"^  \*\s+qwen3-1-7b ", out, re.M) and re.search(r"^  \+\s+qwen3-4b ", out, re.M),
             "spark model list marks the spark pick * and the ember pick +", out)
        t.ok(re.search(r"^   \? gemma3-12b ", out, re.M), "spark model list marks a community row ?", out)
        t.ok("spark ember list -- 2 models with a purpose" in out, "spark model list ends pointing at spark ember list", out)
        t.ok("e = embers (a purpose), u = yours" in out, "the legend names the source marks", out)
        rc, out2, _ = spark("ember", "list", extra=marks)
        t.ok(rc == 0 and re.search(r"^  \*\s+qwen3-1-7b ", out2, re.M) and re.search(r"^  \+\s+qwen3-4b ", out2, re.M),
             "spark ember list prints the same table", out2)
        t.ok(re.search(r"^   e qwen2-5-coder-7b ", out2, re.M) and "      code: reads and writes programs" in out2,
             "spark ember list shows an embers.env row and its purpose line", out2)
        t.ok("spark ember list --" not in out2, "spark ember list has no closing pointer to itself", out2)
        client = {"SPARK_NO_APPLY": "1", "SPARK_MEM_TOTAL_GB": "64", "SITE_AI_MODEL": "none", "SITE_EMBER_MODEL": "auto"}
        rc, out3, _ = spark("ember", "list", extra=client)
        row_lines3 = [ln for ln in out3.splitlines() if " GB file " in ln]
        t.ok(rc == 0 and row_lines3 and not any(re.match(r"^  [*+]", ln) for ln in row_lines3),
             "SITE_AI_MODEL=none: nothing served, so ember auto picks nothing", out3)
        # the speed column: an estimate (~) on every fitting row until measured
        speed_env = {"SPARK_NO_APPLY": "1", "SPARK_MEM_TOTAL_GB": "16"}
        rc, out4, _ = spark("model", "list", extra=speed_env)
        rows = [ln for ln in out4.splitlines() if re.search(r" GB file ", ln)]
        fitting = [ln for ln in rows if " fits " in ln]
        too_big = [ln for ln in rows if " too big" in ln]
        t.ok(rc == 0 and fitting and all(re.search(r" ~\d+ tok/s$", ln) for ln in fitting),
             "spark model list: every fitting row ends in an estimated ~N tok/s", out4)
        t.ok(too_big and all("tok/s" not in ln for ln in too_big), "a too-big row has no speed", out4)
        t.ok(all(len(ln) <= 80 for ln in out4.splitlines()[1:]), "every table row fits 80 columns", out4)
        t.ok(re.search(r"budget \d+ GB \(\d+%\), (metal|vulkan|cpu)$", out4.splitlines()[0]), "the header names the backend", out4)
        # the speed cap and the auto build, the python twin under the pins
        # tests/install_test.sh section 8 puts on bootstrap.sh: 18 GB -> a
        # 10.8 GB curated-only budget (qwen3-14b needs 11, over either
        # way); auto stops at the 3 GB cap on cpu (qwen3-4b), the 6 GB cap
        # on vulkan (qwen3-8b, at 19 GB / 11.4 GB budget, where qwen3-14b
        # would otherwise fit); SITE_AI_BUILD=auto is vulkan when a DRM
        # device reports VRAM, else cpu; a name is never second-guessed,
        # and is looked up in all four lists. The Linux rule is forced
        # (engine.IS_MAC) so the pins mean the same on either OS; this OS
        # as it is comes last (metal on macOS whatever the key says).
        os.makedirs(home + "/drm/card0/device")
        os.makedirs(home + "/nodrm")
        with open(home + "/drm/card0/device/mem_info_vram_total", "w") as f:
            f.write("8589934592\n")
        twin = ("import sys; sys.path.insert(0, %r); from spark import engine, config; engine.IS_MAC = False; "
                "cfg = config.Config(); p = engine.chosen_rows(cfg); "
                "print(p['spark'][0] if p['spark'] else 'none', p['ember'][0] if p['ember'] else 'none', "
                "engine.backend(cfg), engine.cap_note(cfg) or '-')" % os.path.join(REPO, "lib"))

        def linux_pick(**pins):
            e = dict(env, SPARK_NO_APPLY="1", SPARK_SYSFS_DRM=home + "/nodrm", SPARK_MEM_TOTAL_GB="18")
            e.update(pins)
            p = subprocess.run([sys.executable, "-c", twin], capture_output=True, text=True, env=e, timeout=30)
            return p.stdout.strip() or p.stderr.strip()
        t.ok(linux_pick(SITE_AI_BUILD="cpu") == "qwen3-4b none cpu auto stops at 3 GB files on cpu (bigger fits, slower than 8 tok/s)",
             "twin: 18 GB cpu -> qwen3-4b (the 3 GB cap), the note", linux_pick(SITE_AI_BUILD="cpu"))
        t.ok(linux_pick(SITE_AI_BUILD="vulkan", SPARK_MEM_TOTAL_GB="19") == "qwen3-8b none vulkan auto stops at 6 GB files on vulkan (bigger fits, slower than 8 tok/s)",
             "twin: 19 GB vulkan -> qwen3-8b (the 6 GB cap holds back qwen3-14b), the note",
             linux_pick(SITE_AI_BUILD="vulkan", SPARK_MEM_TOTAL_GB="19"))
        t.ok(linux_pick(SPARK_SYSFS_DRM=home + "/drm").startswith("qwen3-8b none vulkan "),
             "twin: SITE_AI_BUILD=auto is vulkan when a DRM device reports VRAM", linux_pick(SPARK_SYSFS_DRM=home + "/drm"))
        t.ok(linux_pick().startswith("qwen3-4b none cpu "), "twin: SITE_AI_BUILD=auto is cpu with no GPU in sysfs", linux_pick())
        t.ok(linux_pick(SITE_AI_BUILD="cpu", SITE_EMBER_MODEL="auto").startswith("qwen3-1-7b qwen3-4b cpu "),
             "twin: ember auto takes the largest under the cap beside the smallest", linux_pick(SITE_AI_BUILD="cpu", SITE_EMBER_MODEL="auto"))
        t.ok(linux_pick(SITE_AI_BUILD="cpu", SITE_AI_MODEL="qwen3-14b") == "qwen3-14b none cpu -",
             "twin: a named model is never second-guessed, no note", linux_pick(SITE_AI_BUILD="cpu", SITE_AI_MODEL="qwen3-14b"))
        t.ok(linux_pick(SITE_AI_BUILD="cpu", SITE_AI_MODEL="qwen2-5-coder-7b") == "qwen2-5-coder-7b none cpu -",
             "twin: a named ember row is picked for spark too, from any list",
             linux_pick(SITE_AI_BUILD="cpu", SITE_AI_MODEL="qwen2-5-coder-7b"))
        t.ok(linux_pick(SITE_AI_BUILD="cpu", SITE_AI_MODEL="gemma3-12b") == "gemma3-12b none cpu -",
             "twin: a named community row is picked for spark too, from any list",
             linux_pick(SITE_AI_BUILD="cpu", SITE_AI_MODEL="gemma3-12b"))
        t.ok(linux_pick(SITE_AI_BUILD="cpu", SPARK_MEM_TOTAL_GB="6") == "qwen3-1-7b none cpu -",
             "twin: 6 GB -> the smallest row, nothing held back", linux_pick(SITE_AI_BUILD="cpu", SPARK_MEM_TOTAL_GB="6"))
        # SITE_AI_BUDGET=30 on the 18 GB rig drops the budget to 5.4 GB:
        # qwen3-4b (5 GB) still fits, qwen3-8b (7 GB) no longer does (it
        # would at the default 60 %, tests/install_test.sh section 8 pins
        # the same rig on bootstrap.sh's twin)
        t.ok(linux_pick(SITE_AI_BUILD="vulkan", SITE_AI_BUDGET="30") == "qwen3-4b none vulkan -",
             "twin: SITE_AI_BUDGET=30 -> qwen3-4b, qwen3-8b no longer fits",
             linux_pick(SITE_AI_BUILD="vulkan", SITE_AI_BUDGET="30"))
        # 24 GB -> a 14.4 GB budget: qwen3-14b (11 GB) fits and, on metal
        # (no cap), is the largest that fits; on cpu the 3 GB cap still
        # stops it at qwen3-4b.
        cap_env = {"SPARK_NO_APPLY": "1", "SPARK_MEM_TOTAL_GB": "24", "SITE_AI_BUILD": "cpu", "SPARK_SYSFS_DRM": home + "/nodrm"}
        rc, out6, _ = spark("model", "list", extra=cap_env)
        if sys.platform == "darwin":
            t.ok(rc == 0 and out6.splitlines()[0].endswith(", metal") and re.search(r"^  \*\s+qwen3-14b ", out6, re.M)
                 and "auto stops" not in out6, "macOS: metal whatever the key says, the largest that fits, no note", out6)
        else:
            t.ok(rc == 0 and out6.splitlines()[0].endswith(", cpu") and re.search(r"^  \*\s+qwen3-4b ", out6, re.M)
                 and "  auto stops at 3 GB files on cpu (bigger fits, slower than 8 tok/s)" in out6.splitlines()[1],
                 "Linux: spark model list marks the capped pick and says what it held back", out6)
        t.ok(all(len(ln) <= 80 for ln in out6.splitlines()[1:]), "the cap note fits 80 columns", out6)
        state = home + "/.local/state/spark"
        os.makedirs(state, mode=0o700, exist_ok=True)
        with open(state + "/bench.jsonl", "a") as f:
            f.write(json.dumps({"ts": "2026-01-01 00:00:00", "model": "Qwen_Qwen3-8B-Q4_K_M.gguf", "engine": "/x",
                                "settings": "ngl=999 fa=auto kv=f16 t=auto", "size": "full", "pp": 242.4, "tg": 8.9}) + "\n")
        rc, out5, _ = spark("model", "list", extra=speed_env)
        row8b = [ln for ln in out5.splitlines() if " qwen3-8b " in ln]
        t.ok(rc == 0 and row8b and row8b[0].endswith(" 9 tok/s") and "~" not in row8b[0],
             "a bench baseline turns the row's speed into a measured 9 tok/s", out5)
        os.remove(state + "/bench.jsonl")

        # spark model budget: the status line names the percent and the GB
        # it buys, then the table; N (10-95) sets SITE_AI_BUDGET and the
        # table header carries the new percent; SPARK_NO_APPLY leaves out
        # the download/restart narration, same as spark model NAME
        rc, outb, _ = spark("model", "budget", extra=speed_env)
        t.ok(rc == 0 and re.search(r"^spark model budget.*\d+% of \d+ GB = \d+ GB$", outb.splitlines()[0]),
             "spark model budget: the percent, the GB it buys", outb)
        t.ok("GB for models" in outb, "spark model budget also prints the table", outb)
        rc, outb2, _ = spark("model", "budget", "5", extra=speed_env)
        t.ok(rc == 2, "spark model budget 5 is below 10: refused", outb2)
        rc, outb3, _ = spark("model", "budget", "30", extra={"SPARK_NO_APPLY": "1"})
        t.ok(rc == 0 and "SITE_AI_BUDGET=30" in outb3, "spark model budget 30 writes the key", outb3)
        t.ok("(30%)" in outb3, "the table header shows the new percent", outb3)
        t.ok("restarting" not in outb3 and "download" not in outb3,
             "SPARK_NO_APPLY: the key and the table only -- no restart or download narration", outb3)
        t.ok("SITE_AI_BUDGET=30" in open(home + "/.config/spark/site.env").read(), "site.env carries the choice")

        # the community list: a name from it is never offered by auto, but
        # spark model NAME still finds it (it accepts any source), prints
        # its license line first, and -- stdin not a tty in this harness,
        # which counts as yes -- writes the key
        rc, out7, err7 = spark("model", "gemma3-12b", extra={"SPARK_NO_APPLY": "1"})
        t.ok(rc == 0 and "gemma3-12b license: Gemma-Terms-of-Use" in out7,
             "spark model NAME on a community row prints the license line", out7 + err7)
        t.ok("not an open-source license" in out7, "... and its note", out7)
        t.ok("SITE_AI_MODEL=gemma3-12b" in open(home + "/.config/spark/site.env").read(),
             "stdin not a tty counts as yes: the key is written", out7)

        # a name in two lists is refused, naming both files (config is
        # data; wrong data is refused) -- config.model_tables is the rule,
        # bootstrap.sh model_rows_all is its twin (tests/install_test.sh)
        user_models = home + "/.config/spark/models.env"
        with open(user_models, "w") as f:
            f.write('MODEL_QWEN3_4B="dup.gguf https://x.invalid/dup.gguf 100 ' + "a" * 64 + ' 1"\n')
            f.write('MODEL_QWEN3_4B_LICENSE="MIT https://x.invalid"\n')
        rc, out8, err8 = spark("model", "list", extra={"SPARK_NO_APPLY": "1"})
        t.ok(rc != 0 and "qwen3-4b" in err8 and "models.env" in err8,
             "a name in two lists (models.env and yours) is refused, naming both", err8)
        os.remove(user_models)
        srv2.shutdown()

        # spark model add: a huggingface.co-shaped path, against the stub
        # (not huggingface.co itself, so --sha256 is required); the name
        # is the file stem, lowered, the quantization token stripped
        content = b"tiny model content, planted for spark model verify below"
        content_sha = hashlib.sha256(content).hexdigest()
        STATE["head_body"] = content
        add_url = url + "/org/repo/resolve/main/tiny-model-Q4_K_M.gguf"
        rc, outa, erra = spark("model", "add", add_url, "--license", "MIT https://x",
                                extra={"SPARK_NO_APPLY": "1"})
        t.ok(rc != 0 and "--sha256" in outa + erra and "huggingface.co" in outa + erra,
             "spark model add: no --sha256 on a non-HF URL is refused, naming --sha256", outa + erra)
        rc, outn, errn = spark("model", "add", add_url, "--sha256", content_sha,
                                extra={"SPARK_NO_APPLY": "1"})
        t.ok(rc != 0 and "--license" in outn + errn,
             "spark model add: no --license is refused, naming the flag", outn + errn)
        rc, outb, errb = spark("model", "add", add_url, "--sha256", content_sha, "--license", "MIT https://x",
                                extra={"SPARK_NO_APPLY": "1"})
        user_models_file = home + "/.config/spark/models.env"
        user_env = open(user_models_file).read()
        t.ok(rc == 0 and re.search(r'MODEL_TINY_MODEL="tiny-model-Q4_K_M\.gguf \S+ \d+ %s \d+"' % content_sha, user_env),
             "spark model add --sha256: the user file gets a 5-field row, name tiny-model", outb + errb + user_env)
        t.ok('MODEL_TINY_MODEL_LICENSE="MIT https://x"' in user_env,
             "spark model add: the license lands too", user_env)
        t.ok("SITE_AI_MODEL=tiny-model\n" in open(home + "/.config/spark/site.env").read(),
             "spark model add delegates to cmd_model([name]): site.env picks it", outb)
        rc, outc, errc = spark("model", "add", add_url, "--sha256", content_sha, "--license", "MIT https://x",
                                extra={"SPARK_NO_APPLY": "1"})
        t.ok(rc != 0 and "~/.config/spark/models.env" in outc + errc,
             "spark model add: a second add of the same URL is refused, naming the user file", outc + errc)

        # spark model verify: a planted download matching tiny-model's sha
        # is ok; corrupted (same size, different bytes) it is bad, with the
        # remedy, and exits 1
        models_dir = home + "/.local/share/spark/models"
        os.makedirs(models_dir, exist_ok=True)
        model_path = os.path.join(models_dir, "tiny-model-Q4_K_M.gguf")
        with open(model_path, "wb") as f:
            f.write(content)
        rc, outv, _ = spark("model", "verify")
        t.ok(rc == 0 and re.search(r"^ok\s+tiny-model\s+sha256 ok \(0\.0 GB\)", outv, re.M),
             "spark model verify: a matching file is ok", outv)
        with open(model_path, "wb") as f:
            f.write(b"X" * len(content))
        rc, outv2, _ = spark("model", "verify")
        t.ok(rc == 1 and "bad" in outv2 and "sha256 MISMATCH" in outv2
             and "spark model rm tiny-model; spark model tiny-model" in outv2,
             "spark model verify: a corrupted file is bad, with the remedy, exit 1", outv2)

        # model rm of a file that is not here: the invocation is wrong, exit 2
        rc, outr, _ = spark("model", "rm", "qwen3-4b", extra={"SPARK_NO_APPLY": "1"})
        t.ok(rc == 2 and "not downloaded" in outr, "spark model rm of an absent file: exit 2", outr)

        # spark check --porcelain: the models row follows the same file
        with open(model_path, "wb") as f:
            f.write(content)
        rc, outp1, _ = spark("check", "--porcelain")
        t.ok(re.search(r"^CAPABILITY\tok\tmodels\t", outp1, re.M),
             "spark check --porcelain: models row ok with a matching file", outp1)
        with open(model_path, "wb") as f:
            f.write(b"X" * len(content))
        rc, outp2, _ = spark("check", "--porcelain")
        t.ok(re.search(r"^CAPABILITY\twarn\tmodels\t", outp2, re.M),
             "spark check --porcelain: models row warn once the file is corrupted", outp2)
        os.remove(model_path)
        os.remove(user_models_file)
        del STATE["head_body"]

        # the shell layer: spark shell (state, on, off), the guards, the help that follows it
        off = {"SPARK_NO_APPLY": "1"}
        rc, out, _ = spark("shell", extra=off)
        t.ok(rc == 0 and "SITE_SHELL=off" in out, "spark shell: the state, off by default", out)
        rc, out, _ = spark("shell", "-h")
        t.ok(rc == 0 and out.splitlines()[0] == "spark shell -- spark's own shell: tmux, starship, micro, fzf, eza, bat, btop",
             "spark shell -h signs (contract 8)", out)
        rc, out, _ = spark("help", extra=off)
        t.ok(rc == 0 and "spark font" not in out and "spark shell on" in out,
             "spark help with the layer off: no spark font, one spark shell on line", out)
        rc, out, _ = spark("help", extra=dict(off, SITE_SHELL="on"))
        t.ok(rc == 0 and "spark font" in out and "the shell (spark shell on)" in out,
             "spark help with SITE_SHELL=on lists the shell block", out)

        # the pager: piped output never touches $PAGER -- a pager that would
        # fail (/bin/false) proves page() never ran it off a tty
        rc, out, _ = spark("help", extra={"PAGER": "/bin/false"})
        t.ok(rc == 0 and "your own AI, on your own machine" in out,
             "spark help piped with PAGER=/bin/false: rc 0, the usage prints", out)
        rc, out, _ = spark("check", "memory", extra={"PAGER": "/bin/false"})
        t.ok(rc == 0 and out.startswith("spark check ") and "memory" in out,
             "spark check piped with PAGER=/bin/false: the report prints", out)
        for verb in ("font", "bar"):
            rc, out, _ = spark(verb, extra=off)
            t.ok(rc == 2 and out.strip() == "spark %s -- the shell layer is off (spark shell on)" % verb,
                 "spark %s refuses while the layer is off, signing" % verb, out)
        rc, out, _ = spark("bootconfig", extra=off)
        t.ok(rc == 2 and out.strip() == "spark bootconfig -- gone: spark quiet (login|boot)",
             "spark bootconfig is gone: one line naming spark quiet, exit 2", out)

        # spark quiet: core start round-trip; login/boot per OS (grammar law)
        rc, out, _ = spark("quiet", "-h", extra=off)
        t.ok(rc == 0 and out.splitlines()[0].startswith("spark quiet -- "), "spark quiet -h signs (contract 8)", out)
        rc, out, _ = spark("quiet", extra=off)
        t.ok(rc == 0 and out.startswith("spark quiet -- start off"), "spark quiet bare: shows, start first", out)
        rc, out, _ = spark("quiet", "start", "on", extra=off)
        t.ok(rc == 0 and "SITE_QUIET_START=yes" in open(home + "/.config/spark/site.env").read(),
             "spark quiet start on writes the key (stored yes|no, spoken on|off)", out)
        rc, out, _ = spark("quiet", "start", extra=off)
        t.ok(rc == 0 and out.splitlines()[0] == "spark quiet start -- on", "spark quiet start bare: shows the one state", out)
        rc, out, _ = spark("quiet", "start", "off", extra=off)
        t.ok(rc == 0 and "SITE_QUIET_START=no" in open(home + "/.config/spark/site.env").read(),
             "spark quiet start off writes it back", out)
        rc, out, _ = spark("quiet", "sideways", extra=off)
        t.ok(rc == 2 and out.startswith("spark quiet -- "), "spark quiet sideways: usage, exit 2", out)
        if sys.platform == "darwin":
            rc, out, _ = spark("quiet", "login", extra=off)
            t.ok(rc == 0 and out.strip() == "spark quiet login -- macOS: no motd, no GRUB",
                 "spark quiet login shows on macOS: nothing there, exit 0", out)
            rc, out, _ = spark("quiet", "login", "on", extra=off)
            t.ok(rc == 2 and out.strip() == "spark quiet login -- macOS: no motd, no GRUB",
                 "spark quiet login on on macOS: nothing to set, exit 2", out)
        else:
            rc, out, _ = spark("quiet", "login", extra=off)
            t.ok(rc == 0 and "the shell layer is off" in out, "spark quiet login shows with the layer off", out)
            rc, out, _ = spark("quiet", "login", "on", extra=off)
            t.ok(rc == 2 and out.strip() == "spark quiet -- the shell layer is off (spark shell on)",
                 "spark quiet login on refuses while the layer is off, signing", out)
            rc, out, _ = spark("quiet", "login", "on", extra=dict(off, SITE_SHELL="on"))
            t.ok(rc == 0 and "SITE_QUIET_LOGIN=yes" in open(home + "/.config/spark/site.env").read(),
                 "spark quiet login on writes the key with the layer on", out)
            spark("quiet", "login", "off", extra=dict(off, SITE_SHELL="on"))
        rc, out, _ = spark("theme", "-h", extra=off)
        t.ok(rc == 0 and out.startswith("spark theme -- "), "spark theme stays usable with the layer off", out)
        # the palette's two runtime files, one writer: spark theme NAME
        # writes theme.env and console-colors (the VT escapes); none removes
        # theme.env and turns console-colors into the one reset escape
        rc, out, _ = spark("theme", "gruvbox-dark", extra=off)
        theme_env = open(home + "/.config/spark/theme.env").read()
        cc = open(home + "/.config/spark/console-colors").read()
        t.ok(rc == 0 and "THEME_BG=#282828\n" in theme_env and "THEME_BTOP=gruvbox_dark\n" in theme_env,
             "spark theme NAME writes theme.env from the palette", theme_env)
        t.ok(cc.startswith("\033]P0282828") and "\033]P9fb4934" in cc and "\033]Pfebdbb2" in cc,
             "console-colors holds the sixteen VT escapes, ansi 0-15 in hex", repr(cc))
        rc, out, _ = spark("theme", "none", extra=off)
        t.ok(rc == 0 and not os.path.exists(home + "/.config/spark/theme.env")
             and open(home + "/.config/spark/console-colors").read() == "\033]R\n",
             "spark theme none removes theme.env and leaves the VT reset", out)
        rc, out, _ = spark("theme", "nosuch", extra=off)
        t.ok(rc == 2 and out.startswith("spark theme -- "), "spark theme nosuch: usage, exit 2", out)
        rc, out, _ = spark("shell", "on", extra=off)
        site_env = open(home + "/.config/spark/site.env").read()
        t.ok(rc == 0 and "SITE_SHELL=on\n" in site_env and "open a new shell" in out,
             "spark shell on writes SITE_SHELL=on and says to open a new shell", out)
        rc, out, _ = spark("shell", extra=off)
        t.ok(rc == 0 and "SITE_SHELL=on" in out and "rc files:" in out, "spark shell: the state, on", out)
        # off hands the rc files AND the rendered look back: spark's links
        # go, a .bak comes back, a render with no .bak is removed -- never
        # an empty husk; the core palette files (theme.env) stay
        rcname = ".zshrc" if sys.platform == "darwin" else ".bashrc"
        os.symlink(os.path.join(REPO, "macos" if sys.platform == "darwin" else "linux", "home", rcname), home + "/" + rcname)
        with open(home + "/" + rcname + ".bak", "w") as f:
            f.write("# mine\n")
        with open(home + "/.tmux.conf", "w") as f:               # a spark render, no .bak
            f.write("# rendered by spark\n")
        os.makedirs(home + "/.config/btop", exist_ok=True)
        with open(home + "/.config/btop/btop.conf", "w") as f:   # a render shadowing a .bak
            f.write("# rendered by spark\n")
        with open(home + "/.config/btop/btop.conf.bak", "w") as f:
            f.write("# pre-spark btop\n")
        with open(home + "/.config/spark/theme.env", "w") as f:  # core: spark theme owns it
            f.write("THEME_BG=#282828\n")
        rc, out, _ = spark("shell", "off", extra=off)
        site_env = open(home + "/.config/spark/site.env").read()
        t.ok(rc == 0 and "SITE_SHELL=off\n" in site_env and "packages stay installed" in out,
             "spark shell off writes SITE_SHELL=off and says the packages stay", out)
        t.ok("restore" in out and not os.path.islink(home + "/" + rcname) and open(home + "/" + rcname).read() == "# mine\n",
             "spark shell off moves the .bak rc file back over spark's link", out)
        t.ok(not os.path.exists(home + "/.tmux.conf") and "tmux.conf" in out,
             "spark shell off removes a rendered .tmux.conf with no .bak (no husk)", out)
        t.ok(open(home + "/.config/btop/btop.conf").read() == "# pre-spark btop\n",
             "spark shell off restores btop.conf from its .bak", out)
        t.ok(os.path.exists(home + "/.config/spark/theme.env"),
             "spark shell off leaves theme.env alone (the theme is core)", out)
        os.remove(home + "/.config/spark/theme.env")
        os.remove(home + "/.config/btop/btop.conf")
        rc, out, _ = spark("shell", "sideways", extra=off)
        t.ok(rc == 2 and out.startswith("spark shell -- "), "spark shell sideways is refused with the usage", out)

        # the client shape: spark client (state, URL, off); the check's client rows
        rc, out, _ = spark("client", extra=off)
        t.ok(rc == 0 and "not a client" in out and "SITE_PEER_AI_URL=unset" in out, "spark client: not a client", out)
        rc, out, _ = spark("client", "192.0.2.10:8081", extra=off)
        t.ok(rc == 2 and out.startswith("spark client -- URL is http://"), "spark client without a scheme is refused", out)
        rc, out, _ = spark("client", "http://192.0.2.10:8081/", extra=off)
        site_env = open(home + "/.config/spark/site.env").read()
        t.ok(rc == 0 and "SITE_PEER_AI_URL=http://192.0.2.10:8081\n" in site_env and "SITE_AI_MODEL=none\n" in site_env
             and "scp 192.0.2.10:~/.local/state/spark/ember-token" in out,
             "spark client URL writes the peer and none, says the scp of the token", out)
        rc, out, _ = spark("client", extra=off)
        t.ok(rc == 0 and "of http://192.0.2.10:8081" in out and "peer" in out and "ember-token" in out,
             "spark client: the state, a client", out)
        rc, outp, _ = spark("check", "--porcelain", "--fresh", extra=dict(off, SITE_PEER_AI_URL="http://192.0.2.10:8081"))
        t.ok(all(re.search(r"^\w+\tna\t%s\ta client of 192.0.2.10:8081" % r, outp, re.M) for r in ("engine", "services", "watchdog", "ai", "serve", "forge")),
             "spark check as a client: engine, services, watchdog, ai, serve, forge are na", outp)
        rc, out, _ = spark("client", "off", extra=off)
        site_env = open(home + "/.config/spark/site.env").read()
        t.ok(rc == 0 and "SITE_AI_MODEL=auto\n" in site_env and "the peer stays first" in out,
             "spark client off hands the model choice back to auto", out)
        rc, out, _ = spark("client", "-h")
        t.ok(rc == 0 and out.splitlines()[0] == "spark client -- a machine that answers from another machine's FORGE",
             "spark client -h signs (contract 8)", out)

        # spark setup: the guided first run, non-interactive, nothing applied
        os.remove(home + "/.config/spark/site.env")
        rc, out, _ = spark("setup", "-h")
        t.ok(rc == 0 and out.splitlines()[0] == "spark setup -- pick the model this machine earns and light it up",
             "spark setup -h signs (contract 8)", out)
        rc, out, _ = spark(extra=off)
        t.ok(rc == 0 and "'s AI on" in out, "bare spark with no site.env, not a tty: the status (the offer is tty-only)", out)
        rc, out, err = spark("setup", "--yes", "--no-serve", "--model", "none", extra=off)
        site_env = open(home + "/.config/spark/site.env").read()
        t.ok(rc == 0 and err == "", "spark setup --yes --no-serve --model none exits 0", out + err)
        t.ok(re.search(r"^SITE_NAME=\S", site_env, re.M) and re.search(r"^SITE_USER=\S", site_env, re.M)
             and "SITE_AI_MODEL=none\n" in site_env and "SITE_SHELL=off\n" in site_env,
             "setup wrote SITE_NAME, SITE_USER, SITE_AI_MODEL=none, SITE_SHELL=off", site_env)
        t.ok("\u2588" in out and "GB for models" in out and "SITE_AI_MODEL=none" in out and "open a new shell" in out
             and "spark ember NAME adds a second brain" in out,
             "setup printed the logo, the table header, the model line and the closing block", out)
        t.ok("no model chosen" in out, "setup with none says how to choose later", out)
        rc, out, _ = spark("setup", "--yes", "--no-serve", "--model", "nosuch", extra=off)
        t.ok(rc == 2 and "no model named nosuch" in out and "auto none qwen3" in out,
             "setup --model nosuch exits 2 naming the table", out)
        os.remove(home + "/.config/spark/site.env")
        rc, out, _ = spark("setup", "--yes", "--no-serve", "--model", "none", extra=dict(off, SITE_NAME="box"))
        site_env = open(home + "/.config/spark/site.env").read()
        t.ok(rc == 0 and "SITE_NAME=box\n" in site_env, "SITE_NAME in the environment pre-answers the name", site_env)
        # a model chosen: the first question goes to the brain (the stub) and
        # is shown as the widget shows it, with the speed the server reported
        rc, out, _ = spark("setup", "--yes", "--model", "qwen3-1-7b", extra=off)
        t.ok(rc == 0 and "? how big is this dir\n* Files over 1G changed this week\n  find . -type f -size +1G -mtime -7\n" in out,
             "setup asks the first question and shows the hint above the command", out)
        t.ok("12.3 tok/s on your first question (spark bench for the full number)" in out,
             "setup prints the measured tok/s of that question", out)
        t.ok("SITE_AI_MODEL=qwen3-1-7b\n" in open(home + "/.config/spark/site.env").read(),
             "setup --model NAME writes the name", out)

    # completion drift guard: every verb the CLI dispatches (bin/spark's
    # VERBS tuple + cli.COMMANDS' keys) appears in completion.bash -- a new
    # verb without a completion word goes loud here. The zsh file shares
    # the same tables; the pty completion test proves both live. Verbs
    # excluded from completion on purpose are named in a comment there,
    # which counts: the guard is about forgetting, not about policy.
    comp = open(os.path.join(REPO, "home", ".config", "spark", "completion.bash")).read()
    verbs_src = re.search(r"^VERBS = \((.*?)\)$", open(SPARK).read(), re.S | re.M).group(1)
    commands_src = re.search(r"^COMMANDS = \{(.*?)\}$", open(os.path.join(REPO, "lib", "spark", "cli.py")).read(),
                             re.S | re.M).group(1)
    wanted = set(re.findall(r'"([^"]+)"', verbs_src)) | set(re.findall(r'"([^"]+)":', commands_src))
    missing = sorted(w for w in wanted
                     if not re.search(r"(?<![A-Za-z-])%s(?![A-Za-z-])" % re.escape(w), comp))
    t.ok(not missing, "completion.bash names every dispatch verb and cli command",
         "missing: " + " ".join(missing))

    # palette drift guard: the page's theme.builtin map is a hand copy of
    # themes/*.env (the page has no build step) -- parse spark.js and
    # compare, name for name and value for value. A palette added to
    # themes/ without its spark.js row, or the reverse, goes loud here.
    js = open(os.path.join(REPO, "lib", "spark", "forge", "spark.js")).read()
    block = re.search(r"builtin: \{(.*?)\n    \}", js, re.S).group(1)
    js_map = {m.group(1): re.findall(r'"(#[0-9a-fA-F]{6})"', m.group(2))
              for m in re.finditer(r'"([a-z0-9-]+)":\s*\[([^\]]*)\]', block)}
    env_map = {}
    tdir = os.path.join(REPO, "themes")
    for fname in sorted(os.listdir(tdir)):
        if not fname.endswith(".env"):
            continue
        with open(os.path.join(tdir, fname)) as f:
            kv = dict(line.strip().split("=", 1) for line in f
                      if "=" in line and not line.startswith("#"))
        env_map[fname[:-4]] = ([kv["THEME_BG"], kv["THEME_FG"], kv["THEME_ACCENT"], kv["THEME_MUTED"]]
                               + [kv["THEME_ANSI_%d" % i] for i in range(16)])
    t.ok(js_map == env_map, "spark.js theme.builtin matches themes/*.env, value for value",
         "js only: %s; themes only: %s; differing: %s" % (
             sorted(set(js_map) - set(env_map)), sorted(set(env_map) - set(js_map)),
             sorted(k for k in set(js_map) & set(env_map) if js_map[k] != env_map[k])))

    srv.shutdown()
    print("smoke: %s" % ("all ok" if not t.fail else "%d FAILED" % t.fail))
    return 1 if t.fail else 0


if __name__ == "__main__":
    sys.exit(main())
