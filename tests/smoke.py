#!/usr/bin/env python3
# spark tests/smoke.py -- the client against a stub llama-server, hermetic.
#
# A stdlib HTTP server on 127.0.0.1:<free port> plays llama-server: /health
# (200, or 503 while "loading"), /v1/models (bearer required), and
# /v1/chat/completions in both shapes -- JSON for `line`, SSE for the CLI.
# Every case runs bin/spark as a subprocess with a throwaway HOME and a
# scrubbed environment, exactly as a shell would.

import glob
import hashlib
import json
import os
import re
import select
import signal
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPARK = os.path.join(REPO, "bin", "spark")
sys.path.insert(0, os.path.join(REPO, "lib"))
from spark import vault  # noqa: E402  -- to open sealed threads in assertions


def read_thread(home, path):
    """The messages of a sealed thread, via the throwaway HOME's login."""
    import base64
    with open(home + "/.local/state/spark/account-key") as f:
        dk = base64.b64decode(f.read().strip())
    return [json.loads(r.decode("utf-8")) for r in vault.read_sealed(path, dk)]
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

    def _sse(self, pieces, finish="stop"):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for piece in pieces:
            self.wfile.write(("data: " + json.dumps({"choices": [{"delta": {"content": piece}}]}) + "\n\n").encode())
        self.wfile.write(("data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": finish}], "timings": TIMINGS}) + "\n\n").encode())
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
        if self.path == "/api/me":
            # a reinstalled box's page server: one user, one token
            if self.headers.get("Authorization") != "Bearer the-new-boxs-token":
                return self._send(401, {"error": "unauthorized"})
            return self._send(200, {"role": "user", "user": "ana"})
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
        if STATE.get("auth_reject") or not self._auth():
            # auth_reject plays a rotated token: every request is 401 now
            return self._send(401, {"error": "unauthorized"})
        if STATE["mode"] == "loading":
            return self._send(503, {"error": "loading model"})
        if STATE["mode"] == "garbage":
            return self._send(200, b"<html>not json</html>", "text/html")
        messages = body["messages"]
        user = messages[-1]["content"]
        STATE["last_user"] = user                     # the newest user message, for the failure checks
        STATE.setdefault("bodies", []).append(body)   # every request, for the editor's checks
        system = messages[0]["content"]
        if "pasted these lines" in system:           # spark line --paste (contract 4)
            reply = {"summary": "downloads and runs a script" if "curl" in user else "two harmless echo lines",
                     "danger": "curl" in user}
            return self._send(200, {"choices": [{"message": {"content": json.dumps(reply)}}], "timings": TIMINGS})
        if "Say what this text is" in system:        # the editor's reading (spark edit ?)
            if STATE.get("read_fail"):
                return self._send(500, {"error": "no reading today"})
            return self._send(200, {"choices": [{"message": {"content": json.dumps({"language": "Portuguese", "kind": "fiction"})}}], "timings": TIMINGS})
        if "turn it into practice questions" in system:   # spark drill (contract 13), a JSON reply
            return self._send(200, {"choices": [{"message": {"content": json.dumps(drill_items(user))}}], "timings": TIMINGS})
        if body.get("stream") and body.get("response_format"):   # spark line (contract 4): its JSON, streamed
            if STATE.get("no_slot") and "id_slot" in body:     # a server that refuses the slot field
                return self._send(400, {"error": {"message": "unknown field id_slot"}})
            doc = json.dumps(answer_json(messages))
            pieces = tuple(doc[i:i + 5] for i in range(0, len(doc), 5))   # small chunks: the parser's work
            if any(w in user for w in ("midcut", "slowhint", "slowdanger")):
                # line 1's fields, then the wire dies (midcut) or the
                # model thinks a while before the hint (slow...)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                cut = doc.index('"hint"')

                def chunk(t):
                    self.wfile.write(("data: " + json.dumps({"choices": [{"delta": {"content": t}}]}) + "\n\n").encode())
                    self.wfile.flush()
                chunk(doc[:cut])
                if "midcut" in user:
                    self.close_connection = True
                    return
                time.sleep(1.5)
                chunk(doc[cut:])
                self.wfile.write(("data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}], "timings": TIMINGS}) + "\n\n").encode())
                self.wfile.write(b"data: [DONE]\n\n")
                return
            return self._sse(pieces)
        if body.get("stream") and "you are not its editor" in system:   # spark edit ? --source
            if "[held]" in user:        # a source with spans held back: quote one of them
                return self._sse(('The code is hidden: ', '"verification code is [held]"', '.\n'))
            return self._sse(('It gives a price: ', '"$39 wired"', ' -- the reader has the answer.'))
        if body.get("stream") and "inside an editor" in system:
            return self._sse(edit_pieces(system, user))
        if body.get("stream") and "you reply with questions" in system:
            return self._sse(ask_pieces())
        if body.get("stream") and "answer from the source" in system:
            return self._sse(read_pieces(user))
        if body.get("stream") and "watch a live stream" in system:
            return self._sse(watch_pieces(user))
        if body.get("stream"):
            # `count` streams how many messages arrived, as the JSON shape does;
            # `wraptest` streams a long plain answer to prove the 80-col wrap
            if "count" in user:
                pieces = (str(len(messages)),)
            elif "stall" in user:
                # half an answer, then silence past the client's timeout
                # (a model that hangs, a server restarted under the reply)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                try:
                    self.wfile.write(("data: " + json.dumps({"choices": [{"delta": {"content": "Half an "}}]}) + "\n\n").encode())
                    self.wfile.flush()
                    time.sleep(3)
                except (BrokenPipeError, ConnectionResetError):
                    pass            # the client gave up first: the point of the test
                return
            elif "wraptest" in user:
                pieces = tuple("word%02d " % i for i in range(1, 41))
            elif "fencetest" in user:
                # a reply in a code fence, its first line of words long
                pieces = ("\n```sh\n", "du -sh " + "word " * 20 + "\n", "```\n")
            elif "capped" in user:
                # the server's cap ended the reply: finish_reason length
                STATE["last_max_tokens"] = body.get("max_tokens")
                return self._sse(("Half an ", "answer"), finish="length")
            else:
                pieces = ("The ", "output ", "means ", "X.")
            return self._sse(pieces)
        self._send(200, {"choices": [{"message": {"content": json.dumps(answer_json(messages))}}], "timings": TIMINGS})


def edit_pieces(system, user):
    """spark edit's replies: a rewrite comes fenced (the fence must go), or
    echoes the text when asked to `keep it`; a completion is a tail; a
    question gets a numbered note."""
    if "You are editing text" in system:
        if user.startswith("keep it"):
            return (user.split(":\n", 1)[1],)
        return ("```markdown\n", "Fixed ", "text.\n", "```\n")
    if "You are completing text" in system:
        return (" and so on.",)
    if STATE.get("ask_quotes"):
        # a review with quotes: one true, one misquote, one across the
        # text's line break, one curly with the comma tucked inside
        return ('1. "Some prose." reads flat\n2. "Sum prose" is mis', 'spelled\n3. "prose. And more" runs on\n',
                '4. “more here,” drifts\n5. "Sum prose" -> "Some verse" reads better\nno newline')
    return ("1. line 2: ", "typo\n")


ASK_TEXT = ("We will move the store to Postgres in March.\n"
            "The migration runs nightly and takes four hours.\n")


def ask_pieces():
    """spark ask's reply (contract 12), one line at a time: a preamble, a
    grounded question, one whose quote is invented, a question that could
    be asked of any plan, a repeat, two more grounded ones (one arriving
    wrapped whole in quotes -- unwrapped before the law reads it) and a
    fourth past the cap. Three survive; five are dropped, each by a
    different rule. STATE['ask_none'] plays the model with nothing to ask."""
    if STATE.get("ask_none"):
        return ("Here are my questions:\n", "The plan looks solid to me.\n",
                'Why does "the rollback plan" exist?\n')
    return ("Here are my questions:\n",
            'What happens if "the migration runs nightly" overr', "uns its window?\n",
            'Why does "the rollback plan" exist?\n',
            "What is your timeline?\n",
            'What happens if "the migration runs nightly" overruns its window?\n',
            '"Who owns "Postgres" after March?"\n',   # wrapped whole: unwrapped, then kept
            'What else could "takes four hours" hide?\n',
            'Is "nightly" the only window?')


READ_TEXT = ("The gate opens at nine and closes at noon.\n"
             "Tickets are two dollars, free for children.\n")


def read_pieces(user=""):
    """spark read's reply (contract 11), line by line: a preamble that
    quotes nothing, a grounded claim (arriving split mid-quote), a claim
    whose quote is invented, and a second grounded claim. Two survive;
    two are dropped, each by its own rule. STATE['read_none'] plays the
    model whose every line fails the law; a `what repeats` question is
    the parts case, answered with a quote every part of `big` holds."""
    if STATE.get("read_none"):
        return ("It is about a gate.\n", 'It costs "ten dollars" to enter.\n')
    if "what repeats" in user:
        return ('It repeats "word word" throughout.\n',)
    return ("Here is what it says:\n",
            'It opens "at nine" and clo', 'ses "at noon".\n',
            'Entry costs "five dollars" for everyone.\n',
            'Children go "free for children".\n')


DRILL_TEXT = ("Mitochondria make ATP for the cell.\n"
              "The cell wall is rigid and gives the cell its shape.\n")


def drill_items(user):
    """spark drill's proposal (contract 13): two items whose answer is a
    verbatim span of the source, one whose answer is invented (dropped by
    the grounding), and a duplicate question (folded away). STATE['drill_thin']
    plays a source with nothing worth drilling."""
    if STATE.get("drill_thin"):
        return {"items": []}
    return {"items": [
        {"question": "What makes ATP?", "answer": "Mitochondria"},
        {"question": "What is invented?", "answer": "the nucleus sings at dawn"},
        {"question": "What is rigid?", "answer": "The cell wall"},
        {"question": "what MAKES atp?", "answer": "Mitochondria"}]}


def watch_pieces(user):
    """spark watch's reply (contract 14): one line quoting the match when a
    500 is in the window, silence otherwise. The quote is a line the window
    holds, so the gate keeps it; an empty stream is silence, not a cut. A
    window holding only "error 5001" draws a quote of "error 500" -- word
    boundaries must refuse it."""
    if "5001" in user:
        return ('Saw "error 500" in the log.\n',)
    if "500" in user:
        # no trailing newline on purpose: the gate must end the line
        # itself, or two matches concatenate and `| while read` starves
        return ('A 500 error appeared: "GET /x 500"',)
    return ()


def is_do(messages):
    """mode do: the system message carries MODE_DO"""
    return "completing a task in steps" in messages[0]["content"]


def answer_json(messages):
    last = messages[-1].get("content", "")
    if "copied CHARACTER FOR CHARACTER" in messages[0].get("content", ""):
        # spark recall: one line that is really in the history, one invented,
        # a substring of a line that ran ("rm -rf /" inside "rm -rf
        # /tmp/build"), a prefix word, and the dangerous line itself.
        # cli.cmd_recall keeps only whole history lines; danger carries !.
        return {"candidates": ["docker network rm $(docker network ls -q)",
                               "docker network prune --force --invented",
                               "rm -rf /", "ls", "rm -rf /tmp/build"]}
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
            return {"kind": "cmd", "command": "echo 26", "hint": "count things", "danger": False,
                    "proof": "test -d ."}
        if "missdo" in goal:                    # the step names a missing binary
            if "is not installed" in user:
                return {"kind": "done", "command": "", "hint": "gave up", "danger": False}
            return {"kind": "cmd", "command": "frobnicate --all", "hint": "scan things", "danger": False}
        if "proofleak" in goal:                 # the proof prints a secret and exits 1
            if "Output of" in user:
                return {"kind": "done", "command": "", "hint": "all done", "danger": False}
            return {"kind": "cmd", "command": "echo ok", "hint": "do it", "danger": False,
                    "proof": "head secret.txt /nonexistent"}
        if "bigout" in goal:                    # never done, 4 kB a step: the budget must cut
            return {"kind": "cmd", "command": "yes 'filler line of output for the budget' | head -n 100",
                    "hint": "print a lot", "danger": False}
        if "leakstep" in goal:                  # a step prints a secret: held before it rides
            if "Output of" in user:
                return {"kind": "done", "command": "", "hint": "all done", "danger": False}
            return {"kind": "cmd", "command": "cat creds.txt", "hint": "read the file", "danger": False}
        if "badflag" in goal or "goodflag" in goal:   # a step refused for an option (or not)
            if "Output of" in user:
                return {"kind": "done", "command": "", "hint": "all done", "danger": False}
            return {"kind": "cmd", "command": "fakeflag --frob" if "badflag" in goal else "fakeflag --ok",
                    "hint": "use the tool", "danger": False}
        outs = sum(1 for m in messages[1:] if m.get("role") == "user" and "Output of" in m.get("content", ""))
        if "boxwork" in goal:                   # a sandboxed run: write, then delete (a danger step), then done
            if outs == 0:
                return {"kind": "cmd", "command": "echo hello >> notes.txt", "hint": "write a note",
                        "danger": False, "proof": "test -f notes.txt"}
            if outs == 1:
                return {"kind": "cmd", "command": "rm -f old.txt", "hint": "drop the old file", "danger": False}
            return {"kind": "done", "command": "", "hint": "wrote notes.txt, removed old.txt", "danger": False}
        if "boxlook" in goal:                   # a sandboxed run that changes nothing
            if outs:
                return {"kind": "done", "command": "", "hint": "looked", "danger": False}
            return {"kind": "cmd", "command": "ls", "hint": "look", "danger": False}
        if "sumstep" in goal or "catsum" in goal:   # checksum lines and a token on one output: a tool's, or cat's
            if outs:
                return {"kind": "done", "command": "", "hint": "all done", "danger": False}
            return {"kind": "cmd", "command": "sha256sum sums.txt" if "sumstep" in goal else "cat sums.txt",
                    "hint": "show the sums", "danger": False}
        if "tokstep" in goal:                   # a step prints one of spark's own tokens
            if outs:
                return {"kind": "done", "command": "", "hint": "all done", "danger": False}
            return {"kind": "cmd", "command": "cat tok.txt", "hint": "read the file", "danger": False}
        if "opaquestep" in goal:                # an interpreter handed its code: not readable from the line
            if outs or "skipped this step" in user:
                return {"kind": "done", "command": "", "hint": "all done", "danger": False}
            return {"kind": "cmd", "command": "sh -c 'echo hi'", "hint": "say hi", "danger": False}
        if "surrogate" in goal:                 # a lone surrogate in the model's JSON
            if outs:
                return {"kind": "done", "command": "", "hint": "all done \udcff", "danger": False}
            return {"kind": "cmd", "command": "echo \udcff hi", "hint": "say \udcff hi", "danger": False}
        if "c1char" in goal or "bidichar" in goal:   # a C1 CSI, or a right-to-left override
            return {"kind": "cmd", "command": "echo \x9b2K hi" if "c1char" in goal else "echo \u202e hi",
                    "hint": "say hi", "danger": False}
        if "diskfill" in goal:                  # a sandboxed step that writes until it is stopped
            if outs:
                return {"kind": "done", "command": "", "hint": "all done", "danger": False}
            return {"kind": "cmd", "command": "i=0; while :; do head -c 65536 /dev/zero > f$i; i=$((i+1)); done",
                    "hint": "fill the disk", "danger": False}
        if "bgwriter" in goal:                  # a sandboxed step that leaves a writer running
            if outs:
                return {"kind": "done", "command": "", "hint": "all done", "danger": False}
            return {"kind": "cmd", "command": "nohup sh -c 'while :; do echo x >> bg.log; sleep 0.1; done' >/dev/null 2>&1 & echo started",
                    "hint": "start a writer", "danger": False}
        if "ctrlchar" in goal:                  # a terminal escape inside the command
            return {"kind": "cmd", "command": "echo \x1b[2K\x1b[1Gbenign; rm -rf junk2",
                    "hint": "say hi\x1b]0;evil\x07", "danger": False}
        if "Output of" in user or "STEP-ONE" in user or "skipped" in user:
            return {"kind": "done", "command": "", "hint": "all done", "danger": False}
        if "rm-plain" in goal:                  # unflagged by the model; the regex must
            return {"kind": "cmd", "command": "rm -rf ./junk", "hint": "delete junk", "danger": False}
        return {"kind": "cmd", "command": "echo STEP-ONE", "hint": "say hello", "danger": False}
    # the streamed line (v1.52): the schema's own order -- kind, danger,
    # command, hint, proof -- so line 1 can go the moment the command closes
    if "midcut" in user or "slowhint" in user:
        return {"kind": "cmd", "danger": False, "command": "ls -la", "hint": "lists everything here",
                "proof": "test -d ."}
    if "slowdanger" in user:        # the model says safe; the command is not
        return {"kind": "cmd", "danger": False, "command": "rm -rf build", "hint": "removes the build",
                "proof": ""}
    if "ctrlline" in user or "c1line" in user or "bidiline" in user:
        # a terminal escape, a C1 CSI, a right-to-left override in the command
        cmd = {"ctrlline": "echo \x1b[2K\x1b[1Ghi; rm -rf junk", "c1line": "echo \x9b2K hi",
               "bidiline": "echo ‮ hi"}[next(k for k in ("ctrlline", "c1line", "bidiline") if k in user)]
        return {"kind": "cmd", "danger": False, "command": cmd, "hint": "says hi", "proof": ""}
    if "escquote" in user:          # escapes the parser must read whole
        return {"kind": "cmd", "danger": False, "command": 'printf "%s\\n" "a\\"b" café',
                "hint": "prints \"a\\\"b\" -- é", "proof": ""}
    if "count" in user:           # how many messages arrived: system + history + user
        return {"kind": "answer", "command": "", "hint": str(len(messages)), "danger": False}
    if "delete" in user:
        return {"kind": "cmd", "command": "find . -name '*.tmp' -delete", "hint": "Delete every .tmp file below here", "danger": True}
    if "rm-plain" in user:      # the model forgets to flag it; the regex must
        return {"kind": "cmd", "command": "rm -rf build", "hint": "Remove the build directory", "danger": False}
    if "prooftest" in user:
        return {"kind": "cmd", "command": "mkdir -p pdir", "hint": "makes the dir",
                "danger": False, "proof": "test -d pdir"}
    if "badproof" in user:
        # a proof that writes is not a proof: cli must refuse to print it
        return {"kind": "cmd", "command": "mkdir -p pdir", "hint": "makes the dir",
                "danger": False, "proof": "rm -rf pdir"}
    if "titletest" in user:
        # a hostile answer carrying a title-setting OSC and a CSI: the
        # widget prints hints into a live terminal, so cli scrubs them
        return {"kind": "answer", "command": "", "hint": "Par\x1b]0;evil\x07is\x1b[31m", "danger": False}
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

    def skip(self, what, why):
        """A case written before the thing it tests: it is here so the
        contract has somewhere to land, and it never passes silently."""
        print("  skip %s   (%s)" % (what, why))


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
                    "SPARK_TIMEOUT": "5", "SPARK_NO_REFRESH": "1", "SPARK_LUA_MUTE": "1", "SHELL": "/bin/bash", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TERM": "xterm-256color"})
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
        # blast radius: with a real build/ under --cwd, line 2 opens with the facts
        btree = os.path.join(home, "blast")
        os.makedirs(os.path.join(btree, "build", "sub"))
        for i in range(4):
            open(os.path.join(btree, "build", "f%d.o" % i), "w").write("x" * 1000)
        open(os.path.join(btree, "build", "sub", "g.o"), "w").write("y" * 500)
        rc, out, _ = spark("line", "--cwd", btree, stdin="rm-plain?")
        lines = out.splitlines()
        t.ok(rc == 0 and lines[0] == "danger\trm -rf build" and lines[1].startswith("<- 5 files,")
             and "5 files" in lines[1], "line: a recursive rm shows the blast radius (files, bytes)", out)
        rc, out, _ = spark("line", "--cwd", btree, stdin="delete the tmp files?")
        t.ok(rc == 0 and out.startswith("danger\t") and "<- " not in out,
             "line: a danger that is not a recursive rm shows no facts", out)
        # the danger set sees the long flags and the hiders (v1.30), and
        # is_dangerous and blast share ONE rm pattern
        from spark import persona as _pers
        _dang = ["rm --recursive build", "rm --force x", "find . -name '*.o' -delete",
                 "rsync -a --delete src/ dst/", "git branch -D topic", "chmod -R 700 d",
                 "> /var/log/syslog", "cd /tmp && > f", "cp x y && rm -rf x"]
        _safe = ["cat a >> log", "rm build.log", "git branch -d topic"]
        t.ok(all(_pers.is_dangerous(c) for c in _dang) and not any(_pers.is_dangerous(c) for c in _safe),
             "danger: --recursive/--force, find -delete, rsync --delete, git branch -D, chmod -R, bare > file",
             str([c for c in _dang if not _pers.is_dangerous(c)] + [c for c in _safe if _pers.is_dangerous(c)]))
        # v1.35: a truncating > anywhere (`echo hi > out.txt` moved from
        # the safe list), sudo anything, and the quiet destroyers
        _dang = ["echo x > ~/.bashrc", "echo hi > out.txt", "sudo apt-get install -y x", "sudo rm -rf /x",
                 "sed -i s/a/b/ f", "sed --in-place=.bak x f", "sed -Ei x f", "cmd | tee out.log", "tee f",
                 "shred -u f", "ls | xargs rm", "find . | xargs -0 rm -f", "mv -f a b", "cp -rf a b",
                 "cp --force a b", "history -c", "git stash drop", "git stash clear"]
        _safe = ["cmd >> f", "cmd > /dev/null", "cmd 2>/dev/null", "cmd >&2", "cmd 2>&1 | less",
                 "cmd >/dev/null 2>&1", "tee -a f", "cmd | tee -a log", "sed -n 1p f", "sed s/a/b/ f",
                 "mv a b", "cp -r a b", "history", "git stash list", "stat -c %s f", "test -f x"]
        t.ok(all(_pers.is_dangerous(c) for c in _dang) and not any(_pers.is_dangerous(c) for c in _safe),
             "danger: > file, sudo, sed -i, tee, shred, xargs rm, mv/cp -f, history -c, git stash drop; "
             ">>, 2>, >&, /dev/null, tee -a stay plain",
             str([c for c in _dang if not _pers.is_dangerous(c)] + [c for c in _safe if _pers.is_dangerous(c)]))
        # v1.50: runit's stops and xbps's removals, a named line each (a
        # service down or its runsv gone, a package gone); the read forms
        # and `sv up` stay plain
        _dang = ["sv down ~/.config/spark/sv/spark-serve", "sv exit /var/service/spark-check", "sv force-stop x",
                 "sv force-shutdown x", "sv kill x", "xbps-remove -y libgomp", "xbps-remove -Ro"]
        _safe = ["sv status ~/.config/spark/sv/spark-serve", "sv check x", "sv up x", "sv restart x",
                 "xbps-query -l", "xbps-install -un", "svlogd -tt d"]
        t.ok(all(_pers.is_dangerous(c) for c in _dang) and not any(_pers.is_dangerous(c) for c in _safe),
             "danger: sv down/exit/force-stop/force-shutdown/kill and xbps-remove; "
             "sv status/check/up/restart, xbps-query and xbps-install -un stay plain",
             str([c for c in _dang if not _pers.is_dangerous(c)] + [c for c in _safe if _pers.is_dangerous(c)]))
        # blast: only the rm segment is counted, a leading cd moves the
        # base, and ~ expands -- `cd X && rm -rf build` counts X/build
        f_cd = _pers.blast("cd %s && rm -rf build" % btree)
        f_seg = _pers.blast("cp a b && rm -rf build", btree)
        _oldhome = os.environ.get("HOME")
        os.environ["HOME"] = home
        try:
            f_tilde = _pers.blast("rm -rf ~/blast/build")
        finally:
            os.environ["HOME"] = _oldhome
        t.ok(all(f.startswith("5 files") for f in (f_cd, f_seg, f_tilde)),
             "blast: the rm segment alone, resolved after cd, ~ expanded", repr((f_cd, f_seg, f_tilde)))
        # command not found (127): a tool spark installs is named offline,
        # with no model call -- the stub brain is never asked
        n0 = STATE["hits"]
        rc, out, _ = spark("line", stdin="install it",
                           extra={"SPARK_EXPLAIN_CMD": "rg foo", "SPARK_EXPLAIN_RC": "127"})
        lines = out.splitlines()
        t.ok(rc == 0 and lines[0].startswith("cmd\t") and "ripgrep" in lines[0]
             and STATE["hits"] == n0,
             "line: a known missing tool (rg) gets its install line with no model call", out)

        # localize: the prefix names THIS OS's side of the pairs, not the other
        import platform as _plat
        from spark import persona as _persona, config as _config
        pfx = _persona.prefix(_config.load(), "bash")
        if _plat.system() == "Darwin":
            t.ok("free is vm_stat" in pfx and "rewrite it for macOS" in pfx and "vm_stat is free" not in pfx,
                 "line: the prefix localizes to macOS, not the other way", pfx[-300:])
        else:
            t.ok("vm_stat is free" in pfx and "rewrite it for this machine" in pfx and "free is vm_stat" not in pfx,
                 "line: the prefix localizes to this Linux, not macOS", pfx[-300:])

        # spark recall: intent search grounded against the history on stdin.
        # the promise is line-level: a candidate survives only when it equals
        # a history line after fold -- "rm -rf /" inside "rm -rf /tmp/build"
        # is a substring, not a command that ran; the dangerous line that DID
        # run prints with the ! mark for the widgets.
        hist = ("ls -la\ndocker network rm $(docker network ls -q)\n"
                "git status\nrm -rf /tmp/build\ncd /tmp\n")
        rc, out, err = spark("recall", "the", "docker", "network", "thing", stdin=hist)
        t.ok(rc == 0 and out.splitlines() == ["docker network rm $(docker network ls -q)",
                                              "!\trm -rf /tmp/build"]
             and "invented" not in out,
             "recall: only whole history lines survive; rm -rf / and ls are dropped; danger carries !", out + "|" + err)
        rc, out, err = spark("recall", stdin=hist)
        t.ok(rc == 1 and "what the command did" in err,
             "recall: no intent is one line on stderr, exit 1", out + "|" + err)
        rc, out, err = spark("recall", "anything", stdin="")
        t.ok(rc == 1 and "no history" in err,
             "recall: empty history is exit 1", out + "|" + err)
        rc, out, _ = spark("line", stdin="what is the capital of France?")
        t.ok(rc == 0 and out.splitlines() == ["answer", "Paris"], "line: answer", out)
        # stdin that is not UTF-8 (one Latin-1 byte): the engine's JSON
        # parser answers HTTP 500 to a lone surrogate, so the byte must
        # reach the wire as the replacement mark instead -- C.UTF-8 turns
        # Python's surrogateescape on (the box), a strict locale crashes
        from spark import text as sparktext
        t.ok(sparktext.utf8("caf\udce9") == "caf\ufffd"
             and sparktext.utf8("ok \U0001f600") == "ok \U0001f600",
             "text.utf8: a lone surrogate becomes the mark, a real astral char passes", "")
        p = subprocess.run([sys.executable, SPARK, "line"],
                           input=b"the capital of France? caf\xe9",
                           capture_output=True, env=env, timeout=30)
        sent = json.dumps(STATE["bodies"][-1])
        t.ok(p.returncode == 0 and "\\udce9" not in sent and "caf\ufffd" in STATE["last_user"],
             "line: a non-UTF-8 byte on stdin reaches the wire as the mark, never a surrogate",
             repr(STATE["last_user"]) + "|" + p.stderr.decode(errors="replace")[:120])
        # a hostile answer carrying escape sequences: scrubbed before the
        # widget can print it into a live terminal
        # paste inspection (contract 4, --paste): no command back, one
        # answer/danger line; a locally dangerous line forces danger; a
        # paste over the cap is one line with NO model call
        rc, out, _ = spark("line", "--paste", stdin="echo a\necho b\n")
        t.ok(rc == 0 and out.splitlines() == ["answer", "two harmless echo lines"],
             "line --paste: a harmless paste is one answer line, no command", repr(out))
        rc, out, _ = spark("line", "--paste", stdin="echo hi\nrm -rf /tmp/xyz\n")
        t.ok(rc == 0 and out.splitlines()[0] == "danger",
             "line --paste: a locally dangerous line forces danger whatever the model says", repr(out))
        _n0 = STATE["hits"]
        rc, out, _ = spark("line", "--paste", stdin="x" * 9000 + "\ny\n")
        t.ok(rc == 0 and out.splitlines()[0] == "answer" and "too big to inspect" in out
             and STATE["hits"] == _n0,
             "line --paste: over 8 kB is one line and NO model call", repr(out))
        # a paste that looks like a secret never leaves: one line naming
        # the shape, no model call; the plain two-line paste above was sent
        _key = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXkt\n-----END OPENSSH PRIVATE KEY-----\n"
        rc, out, _ = spark("line", "--paste", stdin=_key)
        t.ok(rc == 0 and out.splitlines() == ["answer", "looks like a secret (a private key): not sent"]
             and STATE["hits"] == _n0,
             "line --paste: a private key block is held back, NO model call", repr(out))
        rc, out, _ = spark("line", "--paste", stdin="export FOO=1\nTOKEN=abcdefgh1234\n")
        t.ok(rc == 0 and out.splitlines() == ["answer", "looks like a secret (a credential line): not sent"]
             and STATE["hits"] == _n0,
             "line --paste: a TOKEN=... line is held back, NO model call", repr(out))

        # contract 4's proof line: printed when read-only, refused when not
        rc, out, _ = spark("line", stdin="prooftest?")
        t.ok(rc == 0 and out.splitlines() == ["cmd\tmkdir -p pdir", "makes the dir", "proof\ttest -d pdir"],
             "line: a read-only proof rides as the third line", repr(out))
        rc, out, _ = spark("line", stdin="badproof?")
        t.ok(rc == 0 and out.splitlines() == ["cmd\tmkdir -p pdir", "makes the dir"],
             "line: a proof that writes is refused, never printed", repr(out))

        # v1.52: the line streams. The request: the schema in the order the
        # model writes it (kind, danger, command, hint, proof), stream on,
        # the line's own slot
        _lb = STATE["bodies"][-1]
        _sch = _lb.get("response_format", {}).get("json_schema", {}).get("schema", {})
        t.ok(_lb.get("stream") is True and _lb.get("id_slot") == 0
             and list(_sch.get("properties", {})) == ["kind", "danger", "command", "hint", "proof"]
             and _sch.get("required") == ["kind", "danger", "command", "hint", "proof"],
             "line: streamed, slot 0, the schema ordered kind, danger, command, hint, proof",
             json.dumps({k: _lb.get(k) for k in ("stream", "id_slot")}) + json.dumps(_sch)[:200])

        def _timed(words):
            """spark line's lines, each with the seconds it took to arrive"""
            p = subprocess.Popen([sys.executable, SPARK, "line"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, text=True, env=env)
            p.stdin.write(words)
            p.stdin.close()
            t0, got = time.time(), []
            for l in p.stdout:
                got.append((l.rstrip("\n"), time.time() - t0))
            return p.wait(timeout=30), got
        rc, got = _timed("slowhint?")
        t.ok(rc == 0 and [g[0] for g in got] == ["cmd\tls -la", "lists everything here", "proof\ttest -d ."]
             and got[1][1] - got[0][1] > 1.0,
             "line: line 1 is out the moment the command closes, the hint after it", repr(got))
        rc, got = _timed("slowdanger?")
        t.ok(rc == 0 and got and got[0][0] == "danger\trm -rf build" and len(got) > 1 and got[1][1] - got[0][1] > 1.0,
             "line: is_dangerous marks line 1 danger before it goes, whatever the model said", repr(got))
        rc, out, _ = spark("line", stdin="midcut?")
        _ml = out.splitlines()
        t.ok(rc == 1 and len(_ml) == 2 and _ml[0] == "cmd\tls -la" and "mid-reply" in _ml[1]
             and "answer above" not in _ml[1],
             "line: a failure after line 1 is line 2's reason, exit 1", repr(out))
        for _w in ("ctrlline", "c1line", "bidiline"):
            rc, out, _ = spark("line", stdin="%s?" % _w)
            t.ok(rc == 1 and out.splitlines() == ["error", "the model's command carried control characters -- refused"],
                 "line: a control character in the command (%s) refuses the reply before line 1" % _w, repr(out))
        rc, out, _ = spark("line", stdin="escquote?")
        t.ok(rc == 0 and out.splitlines()[:2] == ['cmd\tprintf "%s\\n" "a\\"b" café', 'prints "a\\"b" -- é'],
             "line: the streamed JSON's escapes and a non-ASCII letter come out whole", repr(out))
        STATE["no_slot"] = True
        rc, out, _ = spark("line", stdin="prooftest?")
        STATE["no_slot"] = False
        t.ok(rc == 0 and out.splitlines()[0] == "cmd\tmkdir -p pdir" and "id_slot" not in STATE["bodies"][-1],
             "line: a server that refuses id_slot is asked again without it", repr(out))
        _td = home + "/.local/state/spark/turns"
        _last = [json.loads(l) for f in sorted(os.listdir(_td)) for l in open(os.path.join(_td, f)) if l.strip()][-1]
        t.ok(isinstance(_last.get("cmd_ms"), int) and isinstance(_last.get("ms"), int) and _last["cmd_ms"] <= _last["ms"] + 50
             and not any(k in _last for k in ("line", "command", "hint", "proof", "answer", "cwd")),
             "line: the turn records cmd_ms (the wait to line 1) beside ms, and no words", json.dumps(_last)[:300])
        # the incremental reader, alone: char by char it finds what json
        # finds, escapes and all; a repeated key keeps its first value
        from spark import cli as _cli
        _doc = '{ "kind" : "cmd", "danger":false, "command":"echo \\"a\\\\b\\" \\u00e9 \\ud83d\\ude00", "n": -1.5e2, "x": null, "hint":"h" }'
        _fp = _cli._Fields()
        _seen = []
        for _ch in _doc:
            _seen += _fp.feed(_ch)
        t.ok(_fp.fields == json.loads(_doc) and _fp.state == "done" and [k for k, _v in _seen] == list(json.loads(_doc)),
             "line: _Fields reads the stream char by char as json does", repr(_fp.fields))
        _fp = _cli._Fields()
        _fp.feed('{"command":"ls","command":"rm -rf /"}')
        _bad = _cli._Fields()
        _bad.feed('prose, not JSON {"kind":"cmd"}')
        t.ok(_fp.fields == {"command": "ls"} and _bad.state == "bad" and not _bad.fields,
             "line: _Fields keeps a key's first value; prose stops it", repr((_fp.fields, _bad.state)))
        from spark import persona as _sp
        t.ok(_sp.SENDS[0] == ("line", "the line you typed, with the shell and OS name"),
             "line: what the line sends is unchanged (persona.SENDS)", repr(_sp.SENDS[0]))
        # the user bus over a bare ssh: every systemctl --user call carries
        # XDG_RUNTIME_DIR and the bus address, and a start that fails says so
        from spark import engine as _eng
        _saved = {k: os.environ.pop(k, None) for k in ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")}
        _mac = _eng.IS_MAC
        try:
            _eng.IS_MAC = False
            _benv = _eng.user_bus_env()
            t.ok(_benv["XDG_RUNTIME_DIR"] == "/run/user/%d" % os.getuid()
                 and _benv["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/run/user/%d/bus" % os.getuid(),
                 "user_bus_env: the bus defaults to /run/user/UID when the shell brought none", _benv.get("XDG_RUNTIME_DIR"))
            os.environ["XDG_RUNTIME_DIR"] = "/tmp/rt-x"
            t.ok(_eng.user_bus_env()["XDG_RUNTIME_DIR"] == "/tmp/rt-x", "user_bus_env: a set XDG_RUNTIME_DIR is kept")
            with tempfile.TemporaryDirectory() as _sd:
                _stub = os.path.join(_sd, "systemctl")
                with open(_stub, "w") as f:
                    f.write("#!/bin/sh\necho 'Failed to connect to user scope bus via local transport' >&2\nexit 1\n")
                os.chmod(_stub, 0o755)
                _path = os.environ["PATH"]
                os.environ["PATH"] = _sd + ":" + _path
                import io, contextlib
                _buf = io.StringIO()
                with contextlib.redirect_stdout(_buf):
                    _rc = _eng.kickstart(None)
                t.ok(_rc is False and "systemctl --user start spark-serve failed: Failed to connect to user scope bus" in _buf.getvalue(),
                     "kickstart: a start that did not happen returns False and says why", _buf.getvalue())
                with open(_stub, "w") as f:
                    f.write("#!/bin/sh\nexit 0\n")
                t.ok(_eng.kickstart(None) is True, "kickstart: a start that happened returns True")
                os.environ["PATH"] = _path
        finally:
            _eng.IS_MAC = _mac
            for k, v in _saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        from spark import persona as _pp
        t.ok(_pp.proof_ok("test ! -d build") and _pp.proof_ok("git status") and _pp.proof_ok("systemctl is-active x")
             and not _pp.proof_ok("rm -rf build") and not _pp.proof_ok("git push") and not _pp.proof_ok("ls > f")
             and not _pp.proof_ok("test -d a && rm b"),
             "proof_ok: the allowlist takes read-only heads and refuses writes, compounds, redirects")
        # v1.35: argv-based -- a denied option anywhere, a control
        # character, an unbalanced quote; `head a b` and `test -f` still pass
        t.ok(_pp.proof_ok("head a b") and _pp.proof_ok("test -f x") and _pp.proof_ok("stat -c %s f")
             and _pp.proof_ok("tail -n 5 f") and _pp.proof_ok("git diff --stat")
             and not _pp.proof_ok("git diff --output x") and not _pp.proof_ok("git log --output=x")
             and not _pp.proof_ok("tail -f x") and not _pp.proof_ok("tail -fn 5 x")
             and not _pp.proof_ok("git -c core.pager=x status") and not _pp.proof_ok("git show --textconv HEAD")
             and not _pp.proof_ok("test -f \x1bx") and not _pp.proof_ok('ls "unterminated'),
             "proof_ok: argv-based -- --output, tail -f (in a cluster too), git -c, --textconv, "
             "a control character and a bad quote are refused; head a b and test -f pass")
        # v1.50: sv joins the pairs -- status and check prove a runit
        # service; down, up, a bare sv and xbps-remove never do
        t.ok(_pp.proof_ok("sv status ~/.config/spark/sv/spark-serve") and _pp.proof_ok("sv check /var/service/runsvdir-ana")
             and not _pp.proof_ok("sv down ~/.config/spark/sv/spark-serve") and not _pp.proof_ok("sv up x")
             and not _pp.proof_ok("sv") and not _pp.proof_ok("xbps-remove -ny x"),
             "proof_ok: sv status and sv check are proofs; sv down, sv up, a bare sv and xbps-remove are not")
        rc, out, _ = spark("line", stdin="titletest?")
        t.ok(rc == 0 and out.splitlines() == ["answer", "Paris"] and "\x1b" not in out,
             "line: escape sequences in an answer are scrubbed (title-set, colour)", repr(out))
        from spark import text as _text
        t.ok(_text.scrub("a\x1b]0;evil\x07b\x1b[31mc\x1b[0m\td\x00e\x7ff") == "abc\tdef",
             "scrub: OSC, CSI and control chars go; tabs stay",
             repr(_text.scrub("a\x1b]0;evil\x07b\x1b[31mc\x1b[0m\td\x00e\x7ff")))
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

        # the failure moment: the widget rides the command and its exit
        # code along (one-shot variables); explain names them to the brain,
        # and a command that failed in silence still gets an answer
        env_fail = {"SPARK_EXPLAIN_CMD": "find . -nmae x", "SPARK_EXPLAIN_RC": "1"}
        rc, out, err = spark("explain", stdin="find: -nmae: unknown primary\n", extra=env_fail)
        t.ok(rc == 0 and "means X" in out, "explain: answers with the command riding along", out + err)
        sent = STATE.get("last_user") or ""
        t.ok("Command: find . -nmae x" in sent and "Exit: 1" in sent and "Output:" in sent,
             "explain: the command, the exit code and the output are labelled", sent)
        rc, out, err = spark("explain", stdin="", extra=env_fail)
        t.ok(rc == 0 and "means X" in out, "explain: an empty output still answers when the command is known", out + err)
        t.ok("(none)" in (STATE.get("last_user") or ""), "explain: the empty output is said to be empty", STATE.get("last_user"))
        rc, out, err = spark("explain", stdin="x" * 40000, extra=env_fail)
        t.ok(rc == 0 and "chars cut" in (STATE.get("last_user") or ""),
             "explain: 40 kB of hostile output is cut to the tail with a visible mark", err)

        # last, brain, status, history
        rc, out, _ = spark("last")
        t.ok(rc == 0 and "[explain]" in out and "stub-ember-q4" in out, "last: an explain answered by the ember is recorded as the ember", out)
        rc, _, _ = spark("line", stdin="?biggest dir here", extra={"SPARK_TIMEOUT": "5"})
        rc, out, _ = spark("last")
        t.ok(rc == 0 and "stub-7b-q4" in out, "last: a line turn is recorded as the spark model", out)
        t.ok("12.3 tok/s (prompt 96 tok/s" in out, "last: shows the tokens per second the server reported", out)
        rc, out, _ = spark("stats", "--porcelain")
        t.ok(rc == 0 and "tg_mean\t12.3" in out and "cache_pct\t43" in out, "stats: mean tok/s and cache hits from the turns", out)
        t.ok("mode_line\tturns=" in out and "mode_explain\tturns=" in out and "first_p50=" in out,
             "stats: a row per mode, with its own cache rate and first-line wait", out)
        rc, out, _ = spark("stats")
        t.ok(rc == 0 and "by mode" in out and "line" in out, "stats: the by-mode table at the terminal", out)
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
        t.ok(rc == 0 and out.startswith("spark") and "model    " + url in out, "status", out)

        # off / on
        rc, out, _ = spark("off")
        t.ok(rc == 0 and os.path.exists(home + "/.local/state/spark/off"), "off creates the flag")
        rc, out, _ = spark("status")
        t.ok("off (spark on)" in out, "status says off", out)
        rc, out, _ = spark("on")
        t.ok(rc == 0 and not os.path.exists(home + "/.local/state/spark/off"), "on removes the flag")

        # grammar rule 4: the loop verbs answer -h first, signed (contract 8)
        for sub, first in (("last", "spark last -- the last exchange, with its tok/s"),
                           ("status", "spark status -- the model, prompt line, server, soul, memory, last answer"),
                           ("brain", "spark brain -- what answers right now: the page's server or the engine"),
                           ("off", "spark off -- silence the prompt line, every pane at once"),
                           ("on", "spark on -- the prompt line answers again"),
                           ("history", "spark history -- the threads kept on this machine"),
                           ("ver", "spark ver -- logo, version, credits")):
            rc, out, _ = spark(sub, "-h")
            t.ok(rc == 0 and out.splitlines()[0] == first, "spark %s -h signs (contract 8)" % sub, out)

        # SITE_QUIET_START=yes: bare spark is one line; spark status stays full
        rc, out, _ = spark(extra={"SITE_QUIET_START": "yes"})
        t.ok(rc == 0 and out.strip() == "spark -- chat model stub-ember-q4 at %s (spark status for the rest)" % url,
             "SITE_QUIET_START=yes: bare spark answers with one line", out)
        rc, out, _ = spark("status", extra={"SITE_QUIET_START": "yes"})
        t.ok(rc == 0 and "model    " in out, "spark status stays the full report under quiet start", out)

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

        # spark ver --sbom (v1.36, lib/spark/sbom.py): the JSON and one
        # newline, nothing else -- CycloneDX 1.5 with its four top-level
        # fields and the metadata; one data component per model row of
        # models.env (a throwaway HOME holds no rows of its own), one
        # llama.cpp component per pinned flavour of engine.env; and
        # byte-identical across two runs but for the timestamp
        rc, out, err = spark("ver", "--sbom")
        rc2, out2, _ = spark("ver", "--sbom")
        try:
            doc = json.loads(out)
        except ValueError:
            doc = {}
        meta = doc.get("metadata", {})
        t.ok(rc == 0 and err == "" and out.endswith("}\n") and doc.get("bomFormat") == "CycloneDX"
             and doc.get("specVersion") == "1.5" and doc.get("version") == 1
             and re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$", meta.get("timestamp", ""))
             and meta.get("component", {}).get("name") == "spark" and isinstance(doc.get("components"), list),
             "ver --sbom: the CycloneDX 1.5 JSON alone, its four fields and the metadata", out[:120] + err[:120])
        with open(os.path.join(REPO, "models.env")) as f:
            n_models = len(re.findall(r'(?m)^MODEL_[A-Z0-9_]+="\S+\.gguf ', f.read()))
        with open(os.path.join(REPO, "engine.env")) as f:
            n_flav = len(re.findall(r"(?m)^LLAMA_SHA_[A-Z0-9_]+=[0-9a-f]{64}$", f.read()))
        comps = doc.get("components", [])
        models = [c for c in comps if c.get("type") == "data"]
        flavours = [c for c in comps if c.get("name") == "llama.cpp"]
        t.ok(len(models) == n_models and all(len(c["hashes"][0]["content"]) == 64 and c["licenses"][0]["license"]["name"]
                                             and c["externalReferences"][0]["url"].startswith("https://") for c in models),
             "ver --sbom: one data component per model row, each with its sha256, license and URL",
             "%d components, %d rows" % (len(models), n_models))
        t.ok(len(flavours) == n_flav and len({p["value"] for c in flavours for p in c["properties"]}) == n_flav
             and all(c["purl"].startswith("pkg:github/ggml-org/llama.cpp@") for c in flavours),
             "ver --sbom: one llama.cpp component per pinned flavour, its purl and sha256",
             "%d components, %d pins" % (len(flavours), n_flav))
        t.ok(any(c.get("type") == "platform" and c.get("name") == "python" for c in comps)
             and any(c.get("name", "").startswith("actions/") and len(c.get("version", "")) == 40 for c in comps)
             and any(p == {"name": "spark:family", "value": "debian"} for c in comps for p in c.get("properties", [])),
             "ver --sbom: the python floor, a pinned action and a distro package are in it")

        def _stamped(s):
            return re.sub(r'"timestamp": "[^"]*"', '"timestamp": ""', s)
        t.ok(rc2 == 0 and _stamped(out) == _stamped(out2), "ver --sbom: byte-identical across two runs but the timestamp")
        rc, out, _ = spark("ver", "-h")
        t.ok(rc == 0 and "--sbom" in out, "spark ver -h names --sbom", out)

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
        # a verb that is gone, or a word people reach for, is refused whatever
        # follows -- `spark shell on` never becomes a question for the model
        for gone in (("shell", "on"), ("remember", "a", "fact"), ("stop",), ("talk", "to", "me")):
            hits0 = STATE["hits"]
            rc, out, _ = spark(*gone)
            t.ok(rc == 2 and out.strip() == "spark: no command named %s -- spark help lists them" % gone[0]
                 and STATE["hits"] == hits0,
                 "spark %s: a gone verb answers the no-command line, exit 2, no model call" % " ".join(gone), out)
        hits0 = STATE["hits"]
        rc, out, _ = spark("how", "big", "is", "the", "model")
        t.ok(rc == 0 and out.startswith("* ") and STATE["hits"] > hits0,
             "a real question of several words still reaches the model", out)

        # config hygiene
        with open(home + "/.config/spark/spark.env", "w") as f:
            f.write("SPARK_PORT=8080\nSPARK_MODEL=$(rm -rf /)\n")
        rc, out, err = spark("brain", "--porcelain")
        t.ok(rc == 2 and "spark.env:2" in err, "shell syntax in spark.env refused with the line number", err)
        os.remove(home + "/.config/spark/spark.env")

        # threads: `?` starts one, `?? ` goes on with it (the stub counts the
        # messages). v1.4: threads live sealed in the auto-minted account's
        # store, users/<name>/threads/<id>.sealed
        import glob as _glob

        def tdir():
            ds = _glob.glob(home + "/.local/state/spark/users/*/threads")
            return ds[0] if ds else ""

        spark("history", "clear")
        rc, out, _ = spark("line", stdin="? a")
        rc, out, _ = spark("line", stdin="?? count")
        t.ok(rc == 0 and out.splitlines() == ["answer", "4"], "?? sends system + the 2 earlier messages + the line", out)
        rc, out, _ = spark("line", stdin="? count")
        t.ok(rc == 0 and out.splitlines() == ["answer", "2"], "? starts afresh: system + the line", out)
        threads = tdir()
        t.ok(bool(threads), "an account store was auto-minted", home)
        names = sorted(os.listdir(threads))
        t.ok(len(names) == 2 and all(oct(os.stat(threads + "/" + n).st_mode & 0o777) == "0o600" for n in names), "thread files are 0600", names)
        t.ok(oct(os.stat(threads).st_mode & 0o777) == "0o700", "threads dir is 0700")
        with open(threads + "/" + names[0], "rb") as f:
            blob = f.read()
        t.ok(blob.startswith(b"spark-sealed-v1 thread ") and b"count" not in blob, "the thread file is sealed: magic, no plaintext", blob[:40])
        rc, out, _ = spark("history")
        t.ok(rc == 0 and "2 turns  a" in out and "1 turn  count" in out, "history lists the threads with their turns and title", out)
        rc, out, _ = spark("last")
        t.ok(rc == 0 and "thread " + names[-1][:-7] in out, "last names the thread of the turn", out)
        rc, out, _ = spark("history", "clear")
        t.ok(rc == 0 and "2 threads" in out and not os.listdir(threads), "history clear empties the threads too", out)
        rc, out, _ = spark("line", stdin="?? count", extra={"SPARK_HISTORY": "off"})
        t.ok(rc == 0 and out.splitlines() == ["answer", "2"] and not os.listdir(threads), "SPARK_HISTORY=off: ?? is ?, and no thread is written", out)
        rc, out, _ = spark("what", "does", "count", "mean")
        t.ok(rc == 0 and len(os.listdir(threads)) == 1, "spark <words> starts a thread of its own", out)
        spark("history", "clear")

        # one count: spark user, status and history count the threads that
        # hold a turn -- a header-only file (a failed first turn) and a
        # renamed file (the store refuses it) are neither
        for _q in ("one", "two", "three", "four", "five", "six"):
            spark("line", stdin="? " + _q)
        _held = sorted(os.listdir(threads))
        with open(threads + "/failedfirst01.sealed", "w") as f:
            f.write("spark-sealed-v1 thread failedfirst01\n")
        import shutil as _shutil
        _shutil.copyfile(threads + "/" + _held[0], threads + "/renamed01.sealed")
        rc, out, _ = spark("user")
        t.ok(rc == 0 and re.search(r"^  \S+ +6 threads  ", out, re.M), "spark user counts the threads that hold a turn (6 of 8 files)", out)
        rc, out, _ = spark("status")
        t.ok(rc == 0 and ", 6 threads" in out, "status counts the same 6", out)
        rc, out, _ = spark("history")
        t.ok(rc == 0 and "  threads, newest 5 of 6 (" in out and len(re.findall(r"^  \S+  1 turn  ", out, re.M)) == 5,
             "history lists 5 and says newest 5 of 6", out)
        spark("history", "clear")

        # chat: one turn goes on with the newest thread; the REPL reads stdin
        spark("line", stdin="? a")
        rc, out, _ = spark("chat", "count")
        t.ok(rc == 0 and out.strip() == "* 4", "spark chat <words> continues the newest thread, marked (system + 2 + line)", out)
        t.ok(STATE.get("model") == "ember", "chat: the request names the ember role", str(STATE.get("model")))
        rc, out, _ = spark("chat", stdin="count\n\n/new\ncount\n")
        answers = re.findall(r"^\* (\d+)", out, re.M)
        t.ok(rc == 0 and answers == ["6", "2"], "spark chat REPL: continues (6), /new starts afresh (2), blank ignored", out)
        t.ok("chat>" not in out and "fresh thread" in out, "the REPL piped: no prompt text, says so on /new, ends on EOF", out)
        t.ok("Ctrl-D or /q ends" not in out, "the intro line is for a tty: piped, stdout is the replies alone", out)
        rc, out, err = spark("chat", stdin="count\n")
        t.ok(rc == 0 and re.fullmatch(r"\* \d+", out.strip()) and err == "", "piped chat: stdout is the answer alone, no banner, no `chat> `", repr(out))
        t.ok("* " in out, "chat replies print marked answers", out)
        t.ok(len(os.listdir(threads)) == 2, "the REPL left one thread continued and one new")
        rc, out, _ = spark("chat", "-h")
        t.ok(rc == 0 and out.splitlines()[0] == "spark chat -- a conversation", "spark chat -h signs (contract 8)", out)
        rc, out, _ = spark("talk")
        t.ok(rc == 2 and out.startswith("spark: no command named talk"),
             "spark talk is no command any more (v1.3's stub is gone): a slip, exit 2, no model call", out)
        # the quit grammar: all silent, rc 0, nothing sent to the model
        hits0 = STATE["hits"]
        rc, out, err = spark("chat", stdin=":q\n")
        t.ok(rc == 0 and out == "" and err == "" and STATE["hits"] == hits0,
             "chat: :q quits silently, no model call (the role-played-Exited trap)", repr(out))
        rc, out, err = spark("chat", stdin="exit\n")
        t.ok(rc == 0 and out == "" and err == "" and STATE["hits"] == hits0, "chat: exit quits silently too", repr(out))
        rc, out, err = spark("chat", stdin="\n\n:q\n")
        t.ok(rc == 0 and out == "" and STATE["hits"] == hits0, "chat: blank lines ignored, no model call", repr(out))
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
        t.ok(rc == 0 and "* resuming: older (2 turns)" in out and re.findall(r"^\* (\d+)", out, re.M) == ["6"],
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
        answers = [int(n) for n in re.findall(r"^\* (\d+)", out, re.M)]
        t.ok(rc == 0 and "\033[" not in out and len(answers) == 2 and answers[1] == answers[0] + 2,
             "chat: /clear piped prints no escapes and the thread goes on", repr(out))
        spark("history", "clear")

        # wrap at 80 columns when piped: a long canned answer breaks into
        # short lines
        rc, out, _ = spark("chat", stdin="wraptest\n:q\n")
        lines = out.splitlines()
        t.ok(rc == 0 and all(len(l) <= 79 for l in lines), "chat: wraps at 80 columns when piped", out)
        t.ok(len([l for l in lines if l.strip()]) > 2, "chat: the long answer actually wrapped onto several lines", out)
        spark("history", "clear")

        # status's last: the reply's first line of words, never a fence,
        # cut at a word near 70 characters
        spark("chat", "fencetest")
        rc, out, _ = spark("status")
        _body = [l.strip() for l in out.splitlines() if "du -sh" in l]
        t.ok(rc == 0 and "```" not in out and len(_body) == 1 and _body[0].endswith(" word...")
             and len(_body[0].split(" ", 1)[1]) <= 70,
             "status: last is the reply's first line of words, no fence, cut at a word", out)
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
        t.ok(rc == 0 and "no such file" in err and re.findall(r"^\* (\d+)", out, re.M) == ["2"], "the REPL refuses a bad @FILE and goes on", out + err)
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
        rc, out, _ = spark("memory", "add", "the", "box", "is", "called", "forge")
        t.ok(rc == 0 and "remembered" in out, "spark memory add", out)
        rc, out, _ = spark("memory")
        t.ok(rc == 0 and "  1   the box is called forge" in out, "spark memory lists the fact, numbered", out)
        rc, out, _ = spark("memory", "add", "the", "box", "is", "called", "forge")
        t.ok(rc == 1 and "already" in out, "a duplicate fact is refused", out)
        rc, out, _ = spark("memory", "forget", "nope")
        t.ok(rc == 1, "forget of an unknown fact is refused", out)
        rc, out, err = spark("memory", extra={"SPARK_MEMORY": "maybe"})
        t.ok(rc == 2 and "SPARK_MEMORY" in err, "SPARK_MEMORY=maybe is refused by name", err)
        rc, out, _ = spark("status")
        t.ok(rc == 0 and "  soul     yours, " in out and "  memory   1 fact" in out and " threads" in out, "status shows soul, memory, threads", out)

        # spark edit: the editor's protocol (contract 10)
        rc, out, err = spark("edit", "--type", "markdown", "--name", "a/b/draft.md", "fix", "grammar", stdin="Bad text.\n")
        t.ok(rc == 0 and out == "Fixed text.\n", "edit: a rewrite streams raw text, the fence stripped", repr(out) + err)
        t.ok(STATE.get("model") == "ember", "edit: a rewrite names the ember role", str(STATE.get("model")))
        body = STATE["bodies"][-1]
        sent = json.dumps(body)
        umsg = body["messages"][-1]["content"]
        t.ok(umsg.startswith("fix grammar\n\nFile draft.md (markdown):\nBad text.\n"), "edit: words, then the labelled text", repr(umsg[:80]))
        t.ok("a/b/draft.md" not in sent and "[cwd" not in sent and home not in sent, "edit: no path, no cwd, no HOME in the request", sent[:200])
        t.ok("Output:" not in umsg, "edit: the editor's block carries its own label", repr(umsg[:80]))
        rc, out, _ = spark("edit", "keep", "it", stdin="one\n  two\n\nthree")
        t.ok(rc == 0 and out == "one\n  two\n\nthree", "edit: an unchanged rewrite comes back byte for byte", repr(out))
        # an empty buffer (a new file in micro): words write from nothing,
        # the reply ends with a newline; ? and --at say what is missing
        rc, out, err = spark("edit", "write", "a", "haiku", stdin="")
        umsg = STATE["bodies"][-1]["messages"][-1]["content"]
        t.ok(rc == 0 and out.strip() and out.endswith("\n") and "no text yet: write it" in umsg,
             "edit: an empty text with words is written from nothing, ending with a newline", repr(out) + err)
        rc, out, err = spark("edit", "?", stdin="")
        t.ok(rc == 1 and "nothing to ask about yet" in err, "edit: ? on an empty text says so, exit 1", err)
        rc, out, err = spark("edit", "--at", "0", stdin="")
        t.ok(rc == 1 and "nothing to continue yet" in err, "edit: --at on an empty text says so, exit 1", err)
        rc, out, _ = spark("edit", "--type", "text", "--at", "4", stdin="Once upon a time")
        t.ok(rc == 0 and out == " and so on.", "edit: --at N completes", repr(out))
        t.ok(STATE.get("model") == "spark", "edit: a completion names the spark role", str(STATE.get("model")))
        umsg = STATE["bodies"][-1]["messages"][-1]["content"]
        t.ok("Before the cursor:\nOnce\n\nAfter the cursor:\n upon a time" in umsg, "edit: the completion sends before and after", repr(umsg))
        n0 = len(STATE["bodies"])
        rc, out, _ = spark("edit", "--type", "markdown", "?", "why", stdin="Some prose.\n")
        t.ok(rc == 0 and out == "1. line 2: typo\n", "edit: ? streams the answer", repr(out))
        t.ok(len(STATE["bodies"]) == n0 + 2, "edit: a question is two requests -- the reading, then the answer", str(len(STATE["bodies"]) - n0))
        reading, answer = STATE["bodies"][-2], STATE["bodies"][-1]
        t.ok(reading.get("model") == "spark" and "json_schema" in json.dumps(reading.get("response_format", {})), "edit: the reading is a spark-role JSON request", json.dumps(reading)[:200])
        t.ok(reading["messages"][-1]["content"] == "Some prose.\n", "edit: the reading gets the text alone", repr(reading["messages"][-1]["content"]))
        umsg = answer["messages"][-1]["content"]
        t.ok(umsg.startswith("why\n\nYou read this as: Portuguese, fiction.\nText (markdown):\nSome prose."), "edit: the answer restates the reading", repr(umsg[:120]))
        t.ok(umsg.endswith("Some prose.\n\n\nAnswer in Portuguese."), "edit: the language the model read is the request's last line", repr(umsg[-60:]))
        STATE["read_fail"] = True
        rc, out, _ = spark("edit", "?", stdin="Some prose.\n")
        STATE["read_fail"] = False
        umsg = STATE["bodies"][-1]["messages"][-1]["content"]
        t.ok(rc == 0 and out == "1. line 2: typo\n" and "You read this as" not in umsg and "Answer in" not in umsg, "edit: a failed reading is silent, the answer still streams", repr(umsg[:120]))
        t.ok(umsg.startswith("Review this.\n\n"), "edit: ? alone is a review", repr(umsg[:40]))
        # --source: the reading-discussion posture. The brief the model
        # gets is the discuss brief (a published source, not a draft), not
        # the editor's review brief; the turn is still kind answer, mode
        # edit-discuss; the answer names the fact and carries no editorial
        # verb. The plain ? (no flag) stays the editor's brief.
        page = 'The gadget costs "$39 wired" and forty-two wireless.\n'
        rc, out, _ = spark("edit", "?", "--source", "does", "it", "give", "a", "price", stdin=page)
        sysmsg = STATE["bodies"][-1]["messages"][0]["content"]
        t.ok(rc == 0 and "you are not its editor" in sysmsg and "inside an editor" not in sysmsg,
             "edit ? --source: the discuss brief, not the editor's review brief", repr(sysmsg[:80]))
        t.ok("$39 wired" in out and not re.search(r"(?i)\b(rephrase|numbered|consider adding)\b", out),
             "edit ? --source: names the fact, no editorial suggestion", repr(out))
        _turns = sorted(glob.glob(home + "/.local/state/spark/turns/*.jsonl"))
        lt = json.loads(open(_turns[-1]).read().splitlines()[-1]) if _turns else {}
        t.ok(lt.get("mode") == "edit-discuss" and lt.get("kind") == "answer",
             "edit ? --source: the turn is mode edit-discuss, kind answer", json.dumps(lt)[:160])
        rc, out, _ = spark("edit", "?", "what", "is", "wrong", stdin=page)
        umsg = STATE["bodies"][-1]["messages"][-1]["content"]
        t.ok("Answer in Portuguese" in umsg, "edit ?: a draft is answered in the source's language (the reading pass)", repr(umsg[-120:]))
        rc, out, _ = spark("edit", "?", "--source", "traduza", stdin=page)
        sysmsg = STATE["bodies"][-1]["messages"][0]["content"]
        umsg = STATE["bodies"][-1]["messages"][-1]["content"]
        t.ok("inside an editor" not in sysmsg, "edit ? --source: still the discuss brief")
        t.ok("Answer in the language of the question" in umsg and "Answer in Portuguese" not in umsg,
             "edit ? --source: the reader is answered in the question's language, not the source's", repr(umsg[-140:]))
        rc, out, _ = spark("edit", "?", "why", stdin="Some prose.\n")
        sysmsg = STATE["bodies"][-1]["messages"][0]["content"]
        t.ok("inside an editor" in sysmsg, "edit ?: without --source the editor's brief is unchanged", repr(sysmsg[:60]))
        # a source's secrets are held back before it leaves: a mail with a
        # one-time code, a reset link's token and an API key -- the request
        # carries [held] three times and none of the values, stderr names
        # the shapes, the turn records held=3; an answer quoting [held] is
        # anchored (the anchors read what the model saw)
        _code, _tok, _key = "482913", "Zq8xT3kLmN4pW7vR2s", "sk-" + "abcdefghijklmnopqrstuvwx1234"  # spark:allow-secret
        mail = ("Subject: your sign-in\n\nYour verification code is 482913.\n"  # spark:allow-secret
                "Reset it here: https://192.0.2.7/r?reset=Zq8xT3kLmN4pW7vR2s\n"  # spark:allow-secret
                "Your new key is " + _key + " -- keep it safe.\n")
        n0 = len(STATE["bodies"])
        rc, out, err = spark("edit", "?", "--source", "what", "is", "this", stdin=mail)
        sent = json.dumps(STATE["bodies"][n0:])
        umsg = STATE["bodies"][-1]["messages"][-1]["content"]
        t.ok(rc == 0 and umsg.count("[held]") == 3 and not any(v in sent for v in (_code, _tok, _key)),
             "edit ? --source: a code, a link token and a key are held back, none of them sent",
             repr(umsg[-240:]) + err)
        t.ok(err.strip().splitlines()[:1] == ["spark: held back 3 spans that look like secrets (an API key, "
                                              "a one-time code, a link token) -- the model saw [held]"],
             "edit ? --source: one stderr line names what was held", repr(err))
        _turns = sorted(glob.glob(home + "/.local/state/spark/turns/*.jsonl"))
        lt = json.loads(open(_turns[-1]).read().splitlines()[-1]) if _turns else {}
        t.ok(lt.get("held") == 3 and lt.get("mode") == "edit-discuss", "edit ? --source: the turn records held=3",
             json.dumps(lt)[:200])
        t.ok('"verification code is [held]"' in out and "[not in the text]" not in out and lt.get("unanchored") == 0,
             "edit ? --source: a quote of [held] anchors in what the model saw", repr(out))
        # the hints ride in the same message: a subject as --name, an --about
        # carrying a code are held too, counted in the one line
        rc, out, err = spark("edit", "?", "--source", "--name", "Your verification code is 482913",  # spark:allow-secret
                             "--about", "a mail, PIN 7731", "what", stdin="Hello there.\n")  # spark:allow-secret
        sent = json.dumps(STATE["bodies"][-2:])
        t.ok(rc == 0 and "482913" not in sent and "7731" not in sent
             and "spark: held back 2 spans that look like secrets (a one-time code)" in err,
             "edit ? --source: a code in --name or --about is held back too", sent[-300:] + err)
        # `--` ends the options: a question saying --name cannot eat --source
        rc, out, err = spark("edit", "--source", "--", "?", "why", "--name", stdin=mail)
        umsg = STATE["bodies"][-1]["messages"][-1]["content"]
        t.ok(rc == 0 and umsg.startswith("why --name\n") and umsg.count("[held]") == 3 and _code not in umsg,
             "edit --: the words after it are words, the flags before it hold", repr(umsg[:80]) + err)
        _a = mail.index(_code)          # --sel over the code itself: the offsets follow the held text
        rc, out, err = spark("edit", "?", "--source", "--sel", str(_a - 4), str(_a + len(_code)), "what", stdin=mail)
        umsg = STATE["bodies"][-1]["messages"][-1]["content"]
        t.ok(rc == 0 and "[selection starts]\n is [held]\n[selection ends]" in umsg and _code not in umsg,
             "edit ? --source --sel: the selection's offsets move with what was held", repr(umsg[-300:]))
        rc, out, err = spark("edit", "?", "what", "is", "this", stdin=mail)
        umsg = STATE["bodies"][-1]["messages"][-1]["content"]
        t.ok(rc == 0 and all(v in umsg for v in (_code, _tok, _key)) and "[held]" not in umsg and "held back" not in err,
             "edit ?: without --source the author's text is sent untouched", repr(umsg[-200:]) + err)
        envtext = "HOST=192.0.2.9\nAPI_KEY=" + _key + "\npassword = hunter2hunter2\n"  # spark:allow-secret
        rc, out, err = spark("edit", "keep", "it", stdin=envtext)
        t.ok(rc == 0 and out == envtext and "held back" not in err and _key in STATE["bodies"][-1]["messages"][-1]["content"],
             "edit: a rewrite of a .env text comes back byte for byte, nothing held", repr(out) + err)
        # anchors: every quoted span of a ? answer is checked against the text
        import io
        from spark import text as textmod
        an = textmod.Anchors(io.StringIO(), 'He said "hum" and\nleft the room.\n')
        an.write("1. \"said 'hum' and\" is dry\n2. \"HE SAID\" shouts\n3. \"and left\" runs on\n4. \"He sad\" typo\n5. \"was\" -> \"is\" tense\n")
        an.close()
        t.ok((an.quoted, an.missed) == (5, 2), "anchors: quote marks, case and line breaks fold; a typo and a misquote do not; a proposal is skipped", str((an.quoted, an.missed)))
        # a keeping gate (ask, read, watch) writes lines for a reader or a
        # pipe: the model's trailing spaces (a Markdown hard break) go;
        # Anchors keeps the editor's bytes
        _gs = io.StringIO()
        _g = textmod.Gate(_gs, "one two\n", keep=lambda line, verdict, misses: True)
        _g.write("first line  \nsecond\t \nlast  ")
        _g.close()
        _as = io.StringIO()
        _a = textmod.Anchors(_as, "one two\n")
        _a.write("first line  \n")
        _a.close()
        t.ok(_gs.getvalue() == "first line\nsecond\nlast\n" and _as.getvalue() == "first line  \n",
             "Gate: a kept line ends without trailing spaces; Anchors keeps its bytes", repr((_gs.getvalue(), _as.getvalue())))
        # the floor: a span counts as grounding evidence only when it is
        # substantial -- two words or twelve chars after fold, not all stop
        # words. Quoting "the" against any English text proves nothing.
        g = textmod.Ground("The cat sat on the mat.")
        t.ok(g.verdict('The author proves "the" moon is made of cheese.')[0] == textmod.UNQUOTED,
             "floor: a line whose only span is a stop word is refused (the cheese case)")
        t.ok(g.verdict('It trails off "..." like that.')[0] == textmod.UNQUOTED,
             "floor: a punctuation-only span is refused")
        t.ok(g.verdict('It gapes "   " wide.')[0] == textmod.UNQUOTED,
             "floor: a three-space span is refused")
        t.ok(not textmod.anchor("   ", "spaces    here"),
             "floor: a span that is nothing after fold anchors nowhere, even verbatim")
        t.ok(g.verdict('He proves "the cat sat" happened.')[0] == textmod.GROUNDED
             and g.verdict('He proves "the dog ran" happened.')[0] == textmod.UNGROUNDED,
             "floor: a substantial span still grounds, and still fails honestly")
        # whole: watch and recall anchor at word boundaries in the folded text
        t.ok(not textmod.anchor("500", "took 1500ms", whole=True)
             and textmod.anchor("error 500", "an error 500 came back", whole=True)
             and not textmod.anchor("error 500", "an error 5001 came back", whole=True),
             "anchor whole: a span matches at word boundaries, never inside a longer token")
        STATE["ask_quotes"] = True
        rc, out, _ = spark("edit", "?", stdin="Some prose.\nAnd more here.\n")
        STATE["ask_quotes"] = False
        t.ok(rc == 0 and out == '1. "Some prose." reads flat\n2. "Sum prose" [not in the text] is misspelled\n'
             '3. "prose. And more" runs on\n4. “more here,” drifts\n5. "Sum prose" [not in the text] -> "Some verse" [proposed] reads better\nno newline',
             "edit ?: a misquote is marked where it stands; a proposal after -> is marked [proposed], not checked; the last line flushes", repr(out))
        turns = sorted(glob.glob(home + "/.local/state/spark/turns/*.jsonl"))
        lt = json.loads(open(turns[-1]).read().splitlines()[-1]) if turns else {}
        t.ok(lt.get("kind") == "answer" and lt.get("quotes") == 5 and lt.get("unanchored") == 2,
             "edit ?: the turn counts the quotes and the unanchored ones", json.dumps(lt)[:200])
        # --sel: the whole file on stdin, the question about one part of it
        big = "".join("line %03d of the file\n" % i for i in range(1, 41))
        a, b = big.index("line 020"), big.index("line 022")
        rc, out, _ = spark("edit", "--name", "big.md", "?", "why", "--sel", str(a), str(b), stdin=big)
        umsg = STATE["bodies"][-1]["messages"][-1]["content"]
        t.ok(rc == 0 and "File big.md -- the question is about the part between the marks:\n" in umsg
             and "\n[selection starts]\nline 020 of the file\nline 021 of the file\n\n[selection ends]\n" in umsg
             and "line 001" in umsg and "line 040" in umsg,
             "edit ? --sel: the selection between the marks, the file around it", repr(umsg[:300]))
        reading = STATE["bodies"][-2]["messages"][-1]["content"]
        t.ok(reading.startswith(big[max(0, a - 200):][:20]), "edit ? --sel: the reading starts 200 chars before the selection", repr(reading[:40]))
        huge = "x" * 30000 + "\n" + "y" * 20000 + "\n" + "z" * 30000 + "\n"
        rc, out, _ = spark("edit", "?", "--sel", "30001", "50001", stdin=huge)
        umsg = STATE["bodies"][-1]["messages"][-1]["content"]
        t.ok(rc == 0 and len(umsg) < 17000 and "[... 8000 chars cut ...]" in umsg
             and umsg.count("[... ") == 3 and "[selection starts]" in umsg and "[selection ends]" in umsg,
             "edit ? --sel: a 20 kB selection is clipped inside the marks, the window stays under 16 kB", str(len(umsg)))
        rc, out, _ = spark("edit", "?", "--sel", "5", "2", stdin="short\n")
        t.ok(rc == 2 and "--sel A B are byte offsets" in out, "edit ? --sel out of order is refused", out)
        # --thread: the same id continues the exchange; the text again only when it changed
        n1 = len(STATE["bodies"])
        rc, out, _ = spark("edit", "--name", "t.md", "?", "first", "--thread", "edit-t1", stdin="Some prose.\n")
        rc2, out2, _ = spark("edit", "--name", "t.md", "?", "again", "--thread", "edit-t1", stdin="Some prose.\n")
        msgs2 = STATE["bodies"][-1]["messages"]
        t.ok(rc == 0 and rc2 == 0 and len(STATE["bodies"]) == n1 + 3, "edit ? --thread: the reading runs on the first turn only", str(len(STATE["bodies"]) - n1))
        t.ok(len(msgs2) == 4 and msgs2[1]["role"] == "user" and msgs2[1]["content"].startswith("first\n\n")
             and msgs2[2] == {"role": "assistant", "content": "1. line 2: typo\n"} and msgs2[3]["content"] == "again",
             "edit ? --thread again: the first pair rides, the words alone (the text is unchanged)", json.dumps(msgs2)[:300])
        rc3, out3, _ = spark("edit", "--name", "t.md", "?", "third", "--thread", "edit-t1", stdin="Other prose.\n")
        msgs3 = STATE["bodies"][-1]["messages"]
        t.ok(rc3 == 0 and len(msgs3) == 6 and msgs3[-1]["content"] == "third\n\nFile t.md, as it is now:\nOther prose.\n",
             "edit ? --thread with a changed text sends the text again, labelled as it is now", repr(msgs3[-1]["content"]))
        tfiles = [f for _d, _s, fs in os.walk(home + "/.local/state/spark/users") for f in fs if f == "edit-t1.sealed"]
        t.ok(len(tfiles) == 1, "edit ? --thread: one sealed thread under the account, named by the client", str(tfiles))
        rc4, out4, _ = spark("history")
        t.ok(rc4 == 0 and "edit-t1" in out4, "spark history lists the editor's thread", out4)
        rc5, _, _ = spark("edit", "?", "off", "--thread", "edit-t2", stdin="A.\n", extra={"SPARK_HISTORY": "off"})
        rc6, _, _ = spark("edit", "?", "off", "--thread", "edit-t2", stdin="A.\n", extra={"SPARK_HISTORY": "off"})
        t.ok(rc5 == 0 and rc6 == 0 and len(STATE["bodies"][-1]["messages"]) == 2
             and not [f for _d, _s, fs in os.walk(home + "/.local/state/spark/users") for f in fs if f == "edit-t2.sealed"],
             "edit ? --thread with history off: accepted, nothing kept, every turn alone", str(len(STATE["bodies"][-1]["messages"])))
        rc7, out7, _ = spark("edit", "?", "x", "--thread", "bad id!", stdin="A.\n")
        t.ok(rc7 == 2 and "--thread ID is" in out7, "edit ? --thread with a bad id is refused", out7)
        # the ledger: a declined note is kept per file name and rides the next ?
        rc, out, _ = spark("edit", "--decline", stdin='2. "Some prose." reads flat -- cut it\n')
        t.ok(rc == 2 and "needs --name" in out, "edit --decline without a name is refused", out)
        rc, out, err = spark("edit", "--decline", "--name", "a/b/t.md", stdin='2. "Some prose." reads flat -- cut it\n')
        t.ok(rc == 0 and out == "" and err == "", "edit --decline --name keeps the note, silently", out + err)
        rc, out, _ = spark("edit", "--decline", "--name", "t.md", stdin="3. the ending drags\n")
        lfiles = [os.path.join(d, f) for d, _s, fs in os.walk(home + "/.local/state/spark/users") for f in fs if f == "ledger"]
        t.ok(rc == 0 and len(lfiles) == 1 and oct(os.stat(lfiles[0]).st_mode & 0o777) == "0o600"
             and b"drags" not in open(lfiles[0], "rb").read(),
             "the ledger is one sealed 0600 file under the account", str(lfiles))
        rc, out, _ = spark("edit", "--ledger")
        t.ok(rc == 0 and out.splitlines()[0] == "2 notes, newest first" and "t.md" in out and "the ending drags" in out
             and out.index("drags") < out.index("reads flat"), "edit --ledger lists the notes, newest first, by file", out)
        rc, out, _ = spark("edit", "--ledger", "--name", "other.md")
        t.ok(rc == 0 and out.startswith("other.md: no declined note"), "edit --ledger --name: another file has none", out)
        rc, out, _ = spark("ledger")
        t.ok(rc == 2 and "no command named ledger" in out,
             "spark ledger is not a verb: the unknown-word line, exit 2", out)
        rc, out, _ = spark("edit", "--name", "t.md", "?", stdin="Some prose.\n")
        umsg = STATE["bodies"][-1]["messages"][-1]["content"]
        t.ok(rc == 0 and "\nDeclined before -- do not raise these again:\n- 3. the ending drags\n- 2. \"Some prose.\" reads flat -- cut it\nFile t.md:\n" in umsg,
             "edit ?: the file's declined notes ride above the text, newest first", repr(umsg[:300]))
        rc, out, _ = spark("edit", "--name", "u.md", "?", stdin="Some prose.\n")
        umsg = STATE["bodies"][-1]["messages"][-1]["content"]
        t.ok(rc == 0 and "Declined before" not in umsg, "edit ?: another file's question carries none", repr(umsg[:120]))
        rc, out, _ = spark("edit", "--name", "t.md", "?", stdin="Other words.\n")
        umsg = STATE["bodies"][-1]["messages"][-1]["content"]
        t.ok(rc == 0 and "reads flat" not in umsg and "- 3. the ending drags" in umsg,
             "edit ?: a note whose quote left the text retires; one without a quote rides on", repr(umsg[:200]))
        rc, out, _ = spark("edit", "--ledger", "--name", "t.md")
        t.ok(rc == 0 and out.startswith("t.md: 1 note") and "reads flat" not in out, "the retired note left the file", out)
        for i in range(35):
            spark("edit", "--decline", "--name", "cap.md", stdin="note %02d\n" % i)
        rc, out, _ = spark("edit", "--ledger", "--name", "cap.md")
        t.ok(rc == 0 and out.splitlines()[0].startswith("cap.md: 30 notes") and "note 04" not in out and "note 34" in out,
             "a file keeps its newest 30 notes", out.splitlines()[0])
        rc, out, _ = spark("edit", "--ledger", "clear", "--name", "cap.md")
        rc2, out2, _ = spark("edit", "--ledger")
        t.ok(rc == 0 and "dropped 30 notes for cap.md" in out and rc2 == 0 and out2.startswith("1 note"),
             "edit --ledger clear --name drops one file's", out + out2)
        rc, out, _ = spark("edit", "--ledger", "clear")
        t.ok(rc == 0 and out.startswith("dropped ") and spark("edit", "--ledger")[1].startswith("no declined note"),
             "edit --ledger clear drops them all", out)
        # two writers at once: the .lock beside the sealed file makes
        # load-mutate-save atomic, so no decline is lost to a race
        procs = [subprocess.Popen([sys.executable, SPARK, "edit", "--decline", "--name", "race.md"],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, env=env)
                 for _i in range(6)]
        for i, pr in enumerate(procs):
            pr.stdin.write("race note %d\n" % i)
            pr.stdin.close()
        for pr in procs:
            pr.wait(timeout=30)
        rc, out, _ = spark("edit", "--ledger", "--name", "race.md")
        t.ok(rc == 0 and out.splitlines()[0].startswith("race.md: 6 notes"),
             "ledger: six parallel declines all survive (flock around load-mutate-save)", out.splitlines()[0])
        spark("edit", "--ledger", "clear", "--name", "race.md")
        # local_store: a stale account-key (an earlier login's unwrapped
        # dk) must never seal a freshly minted store -- the minted key
        # becomes the cached one, so a later unlock reads everything
        import base64 as _b64
        _xdg2 = {"XDG_STATE_HOME": home + "/.local/state-stale"}
        _sd2 = home + "/.local/state-stale/spark"
        os.makedirs(_sd2, exist_ok=True)
        os.chmod(_sd2, 0o700)
        with open(_sd2 + "/account", "w") as f:
            f.write("name=ana\ntoken=tok-ana\n")
        with open(_sd2 + "/account-key", "w") as f:
            f.write(_b64.b64encode(os.urandom(32)).decode() + "\n")
        for p in ("/account", "/account-key"):
            os.chmod(_sd2 + p, 0o600)
        rc, _o, _e = spark("edit", "--decline", "--name", "s.md", stdin="the first note\n", extra=_xdg2)
        rc3, out3, _ = spark("edit", "--ledger", "--name", "s.md", extra=_xdg2)
        from spark import vault as _vault
        _wrapped = _vault.unwrap_key(_sd2 + "/users/ana/key", "tok-ana", "ana")
        _cached = _b64.b64decode(open(_sd2 + "/account-key").read().strip())
        t.ok(rc == 0 and rc3 == 0 and "the first note" in out3 and _wrapped == _cached,
             "local_store: the cached account-key IS the minted wrapped key -- a login by token reads it all",
             repr(out3) + (" (keys differ)" if _wrapped != _cached else ""))
        # users/<name>/ there without `key`: the store's key is gone --
        # nothing minted here could read those files: refuse, exit 78
        _xdg3 = {"XDG_STATE_HOME": home + "/.local/state-gonekey"}
        _sd3 = home + "/.local/state-gonekey/spark"
        os.makedirs(_sd3 + "/users/bo", exist_ok=True)
        with open(_sd3 + "/users/bo/token.hash", "w") as f:
            f.write("stale-hash\n")              # the store's marker; `key` is gone
        with open(_sd3 + "/account", "w") as f:
            f.write("name=bo\ntoken=tok-bo\n")
        os.chmod(_sd3 + "/account", 0o600)
        rc, out, err = spark("edit", "--decline", "--name", "x.md", stdin="n\n", extra=_xdg3)
        t.ok(rc == 78 and "key is gone" in err and "spark user login bo" in err,
             "local_store: a store without its key refuses with 78, naming the login", out + err)
        rc, out, _ = spark("edit", "--type", "python", "--about", "a poem", "tighten", stdin="x = 1\n")
        body = STATE["bodies"][-1]
        t.ok(body["messages"][-1]["content"].startswith("tighten\n\nThe author says: a poem\nText (python):\n"), "edit: --about rides above the label", repr(body["messages"][-1]["content"][:80]))
        sys_py = body["messages"][0]["content"]
        rc, out, _ = spark("edit", "--type", "markdown", "tighten", stdin="x = 1\n")
        t.ok(STATE["bodies"][-1]["messages"][0]["content"] == sys_py, "edit: one brief for every filetype -- the system message is byte-identical (prompt cache)")
        rc, out, _ = spark("edit", "--name", "notes.txt", "tighten", stdin="x\n")
        t.ok(STATE["bodies"][-1]["messages"][-1]["content"].startswith("tighten\n\nFile notes.txt:\n"), "edit: no --type, no parenthesis")
        rc, out, _ = spark("edit", "--part", "--type", "python", "--name", "s.py", "add", "a", "docstring", stdin="def f():\n    pass\n")
        umsg = STATE["bodies"][-1]["messages"][-1]["content"]
        t.ok(rc == 0 and umsg.startswith("add a docstring\n\nSelected part of s.py (python):\ndef f():") and "Output:" not in umsg, "edit: --part labels a selection", repr(umsg[:80]))
        rc, out, err = spark("edit", "tighten")
        t.ok(rc == 0 and out.endswith("\n"), "edit: words with no text write from nothing (was a refusal before v1.11)", repr(out) + err)
        rc, out, err = spark("edit", stdin="text")
        t.ok(rc == 2 and "spark edit --" in out, "edit: no words and no --at is the usage, exit 2", out[:60] + err)
        rc, out, err = spark("edit", "--at", stdin="text")
        t.ok(rc == 2 and "needs a value" in out, "edit: a flag without its value", out + err)
        rc, out, err = spark("edit", "shorten", stdin="x" * 13000)
        t.ok(rc == 1 and "select less" in err and out == "", "edit: a 13 kB rewrite is refused, nothing sent", err)
        rc, out, _ = spark("edit", "?", stdin="y" * 40000)
        umsg = STATE["bodies"][-1]["messages"][-1]["content"]
        t.ok(rc == 0 and "[... 24000 chars cut ...]" in umsg and len(umsg) < 17000, "edit: a 40 kB question sends head, cut mark, tail", str(len(umsg)))
        rc, out, _ = spark("edit", "-h")
        t.ok(rc == 0 and out.startswith("spark edit -- "), "edit -h is signed", out[:40])
        threads_before = sum(len(fs) for _d, _s, fs in os.walk(home + "/.local/state/spark/users"))
        rc, out, _ = spark("edit", "fix", stdin="t\n")
        threads_after = sum(len(fs) for _d, _s, fs in os.walk(home + "/.local/state/spark/users"))
        t.ok(threads_after == threads_before, "edit: no thread is written", "%d -> %d" % (threads_before, threads_after))
        turns = sorted(glob.glob(home + "/.local/state/spark/turns/*.jsonl"))
        last_turn = json.loads(open(turns[-1]).read().splitlines()[-1]) if turns else {}
        t.ok(last_turn.get("mode") == "edit-rewrite" and last_turn.get("kind") == "rewrite" and not any(k in last_turn for k in ("line", "answer", "context", "command")),
             "edit: the turn is numbers and enums only", json.dumps(last_turn)[:200])

        # spark ask: the questioner's protocol (contract 12)
        rc, out, _ = spark("ask", "-h")
        t.ok(rc == 0 and out.startswith("spark ask -- "), "ask -h is signed", out[:40])
        rc, out, err = spark("ask", stdin=ASK_TEXT)
        t.ok(rc == 0 and out == ('What happens if "the migration runs nightly" overruns its window?\n'
                                 'Who owns "Postgres" after March?\n'
                                 'What else could "takes four hours" hide?\n'),
             "ask: three questions survive; a preamble, an invented quote, a stock question, "
             "a repeat and a fourth past the cap do not", repr(out) + err)
        t.ok(STATE.get("model") == "ember", "ask: the request names the ember role", str(STATE.get("model")))
        umsg = STATE["bodies"][-1]["messages"][-1]["content"]
        t.ok(umsg.startswith("What does this not answer?\n\nYou read this as: Portuguese, fiction.\nText:\n")
             and "[cwd" not in umsg and "Output:" not in umsg,
             "ask: the reading is restated, the text carries its own label, no cwd", repr(umsg[:110]))
        # the request's LAST line restates the whole task: at a real
        # source's distance the model otherwise answers the task phrase
        # itself, rephrased, and every page came back with no questions
        t.ok(umsg.endswith("Now reply, in Portuguese, with your questions alone: "
                           "at most three, one per line, each ending in its question mark."),
             "ask: the task is restated after the source, in the reading's language", repr(umsg[-130:]))
        turns = sorted(glob.glob(home + "/.local/state/spark/turns/*.jsonl"))
        lt = json.loads(open(turns[-1]).read().splitlines()[-1]) if turns else {}
        t.ok(lt.get("mode") == "ask-questions" and lt.get("kind") == "questions" and lt.get("asked") == 3
             and lt.get("dropped") == 5 and not any(k in lt for k in ("line", "answer", "context")),
             "ask: the turn counts what was asked and what was dropped, and keeps no words", json.dumps(lt)[:200])
        rc, out, _ = spark("ask", "--name", "plan.md", "what", "am", "I", "missing", stdin=ASK_TEXT)
        umsg = STATE["bodies"][-1]["messages"][-1]["content"]
        t.ok(rc == 0 and umsg.startswith("what am I missing\n\n") and "Plan plan.md:\n" in umsg,
             "ask: the words say what is being decided; --name labels the text", repr(umsg[:80]))
        # nothing survives: one line, exit 1, and nothing on stdout
        STATE["ask_none"] = True
        rc, out, err = spark("ask", stdin=ASK_TEXT)
        STATE["ask_none"] = False
        t.ok(rc == 1 and out == "" and "nothing to ask" in err,
             "ask: when every line drops, one line on stderr and exit 1, stdout untouched", repr(out) + err)
        # the ledger (kind ask): an answered question is not asked again
        rc, out, _ = spark("ask", "--answered", stdin="who owns it?")
        t.ok(rc == 2 and "needs --name" in out, "ask --answered without a name is refused", out)
        rc, out, err = spark("ask", "--answered", "--name", "a/b/plan.md",
                             stdin='Who owns "Postgres" after March?\n')
        t.ok(rc == 0 and out == "" and err == "", "ask --answered --name keeps the question, silently", out + err)
        rc, out, _ = spark("ask", "--ledger", "--name", "plan.md")
        t.ok(rc == 0 and out.splitlines()[0].startswith("plan.md: 1 question")
             and "Postgres" in out, "ask --ledger lists the questions answered", out)
        rc, out, _ = spark("edit", "--ledger", "--name", "plan.md")
        t.ok(rc == 0 and out.startswith("plan.md: no declined note"),
             "the ledger's kinds do not see each other: the editor's is empty", out)
        rc, out, err = spark("ask", "--name", "plan.md", stdin=ASK_TEXT)
        t.ok(rc == 0 and "Postgres" not in out and out.count("?") == 3,
             "ask: a question already answered is not asked again -- the one behind it takes the place",
             repr(out) + err)
        umsg = STATE["bodies"][-1]["messages"][-1]["content"]
        t.ok("Answered before -- do not ask these again:\n- Who owns \"Postgres\" after March?\n" in umsg,
             "ask: the answered questions ride above the text", repr(umsg[:220]))
        rc, out, _ = spark("ask", "--ledger", "clear", "--name", "plan.md")
        t.ok(rc == 0 and "dropped 1 question for plan.md" in out, "ask --ledger clear --name drops one text's", out)
        # the pipe-back shape: a question comes back numbered and marked,
        # exactly as the gate printed it -- it must still suppress itself
        rc, out, err = spark("ask", "--answered", "--name", "plan.md",
                             stdin='1. Who owns "Postgres" after March? [not in the text]\n')
        rc2, out2, err2 = spark("ask", "--name", "plan.md", stdin=ASK_TEXT)
        t.ok(rc == 0 and rc2 == 0 and "Postgres" not in out2 and out2.count("?") == 3,
             "ask --answered: a numbered, anchor-marked pipe-back suppresses itself next round",
             repr(out2) + err + err2)
        spark("ask", "--ledger", "clear", "--name", "plan.md")
        # the shape of the law, unit by unit
        from spark import ask as askmod
        t.ok(askmod.generic("What is your timeline?", ASK_TEXT)
             and not askmod.generic("What is your timeline for the nightly migration?", ASK_TEXT)
             and not askmod.generic('Who owns "Postgres" after March?', ASK_TEXT),
             "ask: a stock question is generic; the same phrase about this text's own words is not")
        rc, out, err = spark("ask", stdin="")
        t.ok(rc == 2 and out.startswith("spark ask -- ") and "spark <words>" in out,
             "ask: no text is the usage and where a question goes, exit 2", out[:80] + err)
        rc, out, err = spark("ask", stdin="x" * 13000)
        t.ok(rc == 1 and "at most 12000" in err and out == "", "ask: a 13 kB text is refused, nothing sent", err)
        rc, out, err = spark("ask", "--thread", "bad id!", stdin=ASK_TEXT)
        t.ok(rc == 2 and "--thread ID is" in out, "ask --thread with a bad id is refused", out)
        n0 = len(STATE["bodies"])
        rc, out, _ = spark("ask", "--name", "t2.md", "--thread", "ask-t1", stdin=ASK_TEXT)
        rc2, out2, _ = spark("ask", "--name", "t2.md", "--thread", "ask-t1", "and", "now", stdin=ASK_TEXT)
        msgs = STATE["bodies"][-1]["messages"]
        t.ok(rc == 0 and rc2 == 0 and len(STATE["bodies"]) == n0 + 3 and len(msgs) == 4
             and msgs[-1]["content"] == "and now",
             "ask --thread: the reading runs once, the first pair rides, the same text sends the words alone",
             json.dumps(msgs)[:200])

        # spark read: the reader's protocol (contract 11)
        rc, out, _ = spark("read", "-h")
        t.ok(rc == 0 and out.startswith("spark read -- "), "read -h is signed", out[:40])
        # man's overstrikes (mandoc on Void, macOS's man keep them in a pipe):
        # the source the model sees has the letters once, so the quotes check
        _bold = "".join(c + "\b" + c if c.isalpha() else c for c in READ_TEXT)
        rc, out, err = spark("read", "when", "does", "it", "open", stdin=_bold)
        rc0, out0, _ = spark("read", "when", "does", "it", "open", stdin=READ_TEXT)
        t.ok(rc == rc0 == 0 and out == out0, "read: a man page's bold (X\\bX) reads as the plain text", out + err)
        from spark import text as _txt
        t.ok(_txt.unstrike("N\bNA\bAM\bME\bE _\bs_\bc_\bp") == "NAME scp" and _txt.scrub("B\bBold") == "Bold",
             "unstrike and scrub keep the letter of a bold or an underline", _txt.unstrike("N\bN"))
        # the prompt-line audition's grader (tests/line_audition.py) holds its
        # own rules against canned answers and the tree; no model needed
        _la = subprocess.run([sys.executable, os.path.join(REPO, "tests", "line_audition.py"), "selftest"],
                             capture_output=True, text=True, timeout=60)
        t.ok(_la.returncode == 0 and "selftest: all ok" in _la.stdout,
             "line_audition selftest: the grader's rules hold", (_la.stdout + _la.stderr)[-300:])
        # an empty pipe (ssh -h writes its usage to stderr) is one line
        # naming 2>&1, never the whole usage
        rc, out, _ = spark("read", "how", "I", "use", "ssh", stdin="")
        t.ok(rc == 2 and out.count("\n") == 1 and "the pipe brought no text" in out and "2>&1" in out,
             "read from an empty pipe says so in one line and names 2>&1, exit 2", out)
        rc, out, err = spark("read", "when", "does", "it", "open", stdin=READ_TEXT)
        t.ok(rc == 0 and out == ('It opens "at nine" and closes "at noon".\n'
                                 'Children go "free for children".\n'),
             "read: grounded claims survive; a line that quotes nothing and an "
             "invented quote do not", repr(out) + err)
        t.ok(STATE.get("model") == "ember", "read: the request names the ember role", str(STATE.get("model")))
        umsg = STATE["bodies"][-1]["messages"][-1]["content"]
        t.ok(umsg.startswith("when does it open\n\nYou read this as: Portuguese, fiction.\nSource:\n")
             and "[cwd" not in umsg and "Output:" not in umsg,
             "read: the reading is restated, the source carries its own label, no cwd", repr(umsg[:110]))
        turns = sorted(glob.glob(home + "/.local/state/spark/turns/*.jsonl"))
        lt = json.loads(open(turns[-1]).read().splitlines()[-1]) if turns else {}
        t.ok(lt.get("mode") == "read-source" and lt.get("kind") == "read" and lt.get("kept") == 2
             and lt.get("dropped") == 2 and lt.get("part") == 1 and lt.get("parts") == 1
             and not any(k in lt for k in ("line", "answer", "context")),
             "read: the turn counts parts and kept lines, and keeps no words", json.dumps(lt)[:200])
        t.ok(isinstance(lt.get("first_ms"), int) and 0 <= lt["first_ms"] <= lt.get("ms", 0),
             "read: the turn keeps the wait to the first kept line", json.dumps(lt)[:200])
        rt = json.loads(open(turns[-1]).read().splitlines()[-2]) if turns else {}
        t.ok(rt.get("mode") == "edit-read" and rt.get("kind") == "reading" and rt.get("chars") == len(READ_TEXT[:800])
             and isinstance(rt.get("ms"), int) and not any(k in rt for k in ("line", "answer", "context")),
             "read: the reading pass is a turn of its own, numbers only, right before the answer's", json.dumps(rt)[:200])
        rb = STATE["bodies"][-2]        # the reading pass, right before the answer
        t.ok(rb.get("model") == "spark" and "json_schema" in str(rb) and rb.get("temperature") == 0,
             "read: the reading pass is greedy, so the restated reading is the same bytes on the same source",
             "%s %s" % (rb.get("model"), rb.get("temperature")))
        rc, _out, _ = spark("read", stdin=READ_TEXT)
        umsg = STATE["bodies"][-1]["messages"][-1]["content"]
        t.ok(rc == 0 and umsg.startswith("What does this source cover?\n\n"),
             "read: bare asks what the source covers", repr(umsg[:50]))
        # a source always has its secrets held back: the reading and the
        # answer see [held], never the values; one stderr line; held=N
        n0 = len(STATE["bodies"])
        rc, out, err = spark("read", "when", "does", "it", "open", stdin=READ_TEXT + mail)
        sent = json.dumps(STATE["bodies"][n0:])
        umsg = STATE["bodies"][-1]["messages"][-1]["content"]
        t.ok(rc == 0 and umsg.count("[held]") == 3 and not any(v in sent for v in (_code, _tok, _key))
             and "spark: held back 3 spans that look like secrets (" in err,
             "read: a source's code, link token and key are held back, none of them sent", repr(umsg[-200:]) + err)
        turns = sorted(glob.glob(home + "/.local/state/spark/turns/*.jsonl"))
        lt = json.loads(open(turns[-1]).read().splitlines()[-1]) if turns else {}
        t.ok(lt.get("held") == 3 and lt.get("mode") == "read-source", "read: the turn records held=3", json.dumps(lt)[:200])
        rc, out, err = spark("read", stdin="The code on the door is 4417, the gate code.\n")  # spark:allow-secret
        t.ok("spark: held back 1 span that looks like a secret (a one-time code) -- the model saw [held]" in err
             and "4417" not in json.dumps(STATE["bodies"][-2:]),
             "read: one span held is said in the singular", repr(err))
        # the shapes a mail takes: a code before its word, split digits,
        # every token parameter of a link; and a crafted megabyte holds fast
        from spark import text as _text
        for _src, _left in (("482913 is your verification code", "482913"),  # spark:allow-secret
                            ("G-482913 is your Google verification code", "482913"),  # spark:allow-secret
                            ("Your code: 482 913", "482 913"),  # spark:allow-secret
                            ("PIN 48-29-13 today", "48-29-13"),  # spark:allow-secret
                            ("https://192.0.2.7/r?reset=AAAAAAAAAAAAAAAA&sig=BBBBBBBBBBBBBBBB", "BBBB"),  # spark:allow-secret
                            ("https://192.0.2.7/a?oobCode=CCCCCCCCCCCCCCCC&resetToken=DDDDDDDDDDDDDDDD&otp=EEEEEEEEEEEEEEEE",  # spark:allow-secret
                             "CCCC DDDD EEEE")):
            _h, _names = _text.hold_secrets(_src)
            t.ok(_names and not any(v in _h for v in _left.split(" ") if len(v) > 3) and _left not in _h
                 and _text.hold_secrets(_h)[1] == [],
                 "hold: %r holds its secret" % _src[:44], _h)
        for _what, _d in (("a URL that never ends", "http://" * 285 + "?" + "_" * 1000000),
                          ("a megabyte of codes", ("pin: 12-34 https://x?token=" + "a" * 40 + " ") * 15000)):
            _t0 = time.time()
            _text.held_spans(_d)
            _dt = time.time() - _t0
            t.ok(_dt < 1.0, "hold: %s (%d chars) holds in under a second" % (_what, len(_d)), "%.2fs" % _dt)
        # nothing survives: one line composed from the source, exit 1, stdout untouched
        STATE["read_none"] = True
        rc, out, err = spark("read", "who", "wrote", "it", stdin=READ_TEXT)
        STATE["read_none"] = False
        t.ok(rc == 1 and out == "" and 'it opens: "The gate opens at nine' in err,
             "read: when every line drops, the refusal shows the source's own opening words",
             repr(out) + err)
        # parts: 16 kB each, and the answer's first line names the one it read
        big = "word " * 8000                       # 40000 chars -> 3 parts
        from spark import read as readmod
        t.ok(readmod.parts_of(len(big)) == 3
             and readmod.part_slice(big, 1)[-readmod.PART_OVERLAP:] == readmod.part_slice(big, 2)[:readmod.PART_OVERLAP],
             "read: three parts of 40000 chars, each opening with the last 400 of the one before")
        n0 = len(STATE["bodies"])
        rc, out, err = spark("read", "what", "repeats", stdin=big)
        t.ok(rc == 1 and out == "" and "3 parts" in err and "--part N" in err
             and len(STATE["bodies"]) == n0,
             "read: a source past 16 kB is refused with the part count, nothing sent", err)
        rc, out, err = spark("read", "--part", "2", "what", "repeats", stdin=big)
        t.ok(rc == 0 and out == '[part 2 of 3]\nIt repeats "word word" throughout.\n',
             "read: --part 2 answers, and the first line names the part it read", repr(out[:60]) + err)
        rc, out, _ = spark("read", "--part", "9", stdin=big)
        t.ok(rc == 2 and "no part 9" in out, "read: a part past the source is refused, exit 2", out)
        rc, out, _ = spark("read", "--part", "x", stdin=READ_TEXT)
        t.ok(rc == 2 and "--part N is" in out, "read: --part takes a number", out)
        # the ledger (kind read): the questions asked, recorded, never suppressing
        rc, out, err = spark("read", "--name", "a/b/page.txt", "when", "does", "it", "open", stdin=READ_TEXT)
        t.ok(rc == 0 and '"at nine"' in out, "read --name answers and records the question", err)
        rc, out, _ = spark("read", "--ledger", "--name", "page.txt")
        t.ok(rc == 0 and out.splitlines()[0].startswith("page.txt: 1 question")
             and "when does it open" in out, "read --ledger lists the questions asked, basenamed", out)
        rc, out, _ = spark("ask", "--ledger", "--name", "page.txt")
        t.ok(rc == 0 and out.startswith("page.txt: no question answered"),
             "the ledger's kinds do not see each other: the questioner's is empty", out)
        rc, out, err = spark("read", "--name", "page.txt", "when", "does", "it", "open", stdin=READ_TEXT)
        t.ok(rc == 0 and '"at nine"' in out,
             "read: a question asked twice is answered twice -- the ledger never suppresses", repr(out))
        rc, out, _ = spark("read", "--ledger", "clear", "--name", "page.txt")
        t.ok(rc == 0 and "dropped 1 question for page.txt" in out,
             "read --ledger clear --name drops one source's", out)
        rc, out, err = spark("read", stdin="")
        t.ok(rc == 2 and out.startswith("spark read -- the pipe brought no text") and out.count("\n") == 1,
             "read: an empty pipe with no words is the same one line, exit 2", out[:80] + err)
        # a name that arrived as a lone surrogate (a byte that was not UTF-8
        # in argv under surrogateescape: a w3m page title on the box) is
        # kept as strict UTF-8 -- the store's encode never crashes after
        # the answer, and the same title lists and clears the same records
        rc, out, err = spark("read", "--name", "t\udce9tulo.txt", "when", "does", "it", "open", stdin=READ_TEXT)
        t.ok(rc == 0 and '"at nine"' in out and "Traceback" not in err,
             "read --name with a lone surrogate answers and records, no crash", err[-200:])
        rc, out, _ = spark("read", "--ledger", "--name", "t\udce9tulo.txt")
        t.ok(rc == 0 and out.splitlines()[0].startswith("t\ufffdtulo.txt: 1 question"),
             "the ledger lists it under the name as strict UTF-8", out)
        rc, out, _ = spark("read", "--ledger", "clear", "--name", "t\udce9tulo.txt")
        t.ok(rc == 0 and "dropped 1 question" in out, "and clears it by the same name", out)
        from spark import text as _txt
        t.ok(_txt.clean({"a": ["x\udce9", {"b": "\udce9"}], "n": 1}) == {"a": ["x\ufffd", {"b": "\ufffd"}], "n": 1},
             "text.clean: every string in a record strict UTF-8, the rest untouched")
        # the wait is something to read: at a terminal stderr says `reading
        # ...` while the reading pass runs, then what it named; a pipe sees
        # nothing of it (stdout and stderr stay the contract's)
        import pty as _pty
        import select as _sel
        _m, _s = _pty.openpty()
        _p = subprocess.Popen([sys.executable, SPARK, "read", "when", "does", "it", "open"],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=_s, env=env, text=True)
        os.close(_s)
        _p.stdin.write(READ_TEXT)
        _p.stdin.close()
        _tty, _end = b"", time.time() + 30
        while time.time() < _end:
            r, _, _ = _sel.select([_m], [], [], 0.2)
            if r:
                try:
                    chunk = os.read(_m, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                _tty += chunk
            elif _p.poll() is not None:
                break
        os.close(_m)
        _out = _p.stdout.read()
        _p.wait(timeout=30)
        _tty = _tty.decode("utf-8", "replace").replace("\r\n", "\n")
        t.ok(_p.returncode == 0 and "reading ... Portuguese, fiction\n" in _tty and '"at nine"' in _out and "reading" not in _out,
             "read at a terminal: stderr shows the reading pass as it runs, stdout stays the answer", repr(_tty[:80]) + repr(_out[:60]))
        rc, out, err = spark("read", "when", "does", "it", "open", stdin=READ_TEXT)
        t.ok(rc == 0 and '"at nine"' in out and "reading" not in err,
             "read in a pipe: nothing of the reading pass on stderr", repr(err[:80]))

        # spark drill: the practice protocol (contract 13)
        from spark import drill as drillmod
        rc, out, _ = spark("drill", "-h")
        t.ok(rc == 0 and out.startswith("spark drill -- "), "drill -h is signed", out[:40])
        kept = drillmod._ground([{"question": "Q1", "answer": "Mitochondria"},
                                 {"question": "Q2", "answer": "no such words in the source"},
                                 {"question": "Q3", "answer": "The cell wall"}], DRILL_TEXT)
        t.ok([k["answer"] for k in kept] == ["Mitochondria", "The cell wall"],
             "drill: an item whose answer is not in the source is dropped before it is asked", str(kept))
        # the schedule, pure: three misses widen 1 -> 3 -> 7; right twice rests
        m, s, days = 0, 0, []
        for _ in range(3):
            m, s, d = drillmod.schedule(m, s, False)
            days.append(d)
        t.ok(days == [1, 3, 7], "drill: a missed item comes back on a widening interval", str(days))
        _m1, _s1, d1 = drillmod.schedule(0, 0, True)
        _m2, s2, d2 = drillmod.schedule(_m1, _s1, True)
        t.ok(d1 == drillmod.INTERVALS[0] and d2 is None and s2 == drillmod.RIGHT_TWICE,
             "drill: right once comes back soon, right twice in a row rests", "%s %s" % (d1, d2))
        rc, out, err = spark("drill", stdin="")
        t.ok(rc == 2 and out.startswith("spark drill -- ") and "spark <words>" in out,
             "drill: no source is the usage and where a question goes, exit 2", out[:60] + err)
        STATE["drill_thin"] = True
        rc, out, err = spark("drill", stdin=DRILL_TEXT, extra={"SPARK_DRILL_TTY": os.devnull})
        STATE["drill_thin"] = False
        t.ok(rc == 1 and out == "" and "too little" in err,
             "drill: too little to drill is one line, exit 1, never padded", err)
        # a graded session: the answers come from the seam file (reveal, yes/no per item)
        ansfile = home + "/drill-answers.txt"
        with open(ansfile, "w") as f:
            f.write("\nyes\n\nno\n")            # item 1 right, item 2 wrong
        rc, out, err = spark("drill", "--name", "bio", stdin=DRILL_TEXT, extra={"SPARK_DRILL_TTY": ansfile})
        t.ok(rc == 0, "drill --name: a graded session runs to the end", err[:160])
        rc, out, _ = spark("drill", "--ledger", "--name", "bio")
        t.ok(rc == 0 and "2 item" in out and "streak 1" in out and "misses 1" in out,
             "drill --name: the graded items are scheduled -- one right, one to revisit", out)
        rc, out, _ = spark("drill", "--ledger", "clear", "--name", "bio")
        t.ok(rc == 0 and "dropped 2 item" in out, "drill --ledger clear drops the schedule", out)
        # no terminal to answer at is the invocation's fault: signed, exit 2
        rc, out, err = spark("drill", stdin=DRILL_TEXT, extra={"SPARK_DRILL_TTY": home + "/no-such-tty"})
        t.ok(rc == 2 and out.startswith("spark drill -- no terminal to answer at") and "Traceback" not in err,
             "drill: no tty is a signed refusal, exit 2", out[:80] + err[:80])
        # the terminal is looked for before the model is asked: no tty and no
        # engine is the tty refusal (2), never the engine's error (1)
        rc, out, err = spark("drill", stdin=DRILL_TEXT, extra={"SPARK_DRILL_TTY": home + "/no-such-tty",
                                                              "SPARK_BASE_URL": "http://127.0.0.1:9"})
        t.ok(rc == 2 and out.startswith("spark drill -- no terminal to answer at"),
             "drill: no tty refuses before the model is asked", out[:80] + err[:80])
        # no brain is the world's fault: one line, exit 1, never a traceback
        rc, out, err = spark("drill", stdin=DRILL_TEXT, extra={"SPARK_BASE_URL": "http://127.0.0.1:9", "SPARK_DRILL_TTY": os.devnull})
        t.ok(rc == 1 and out == "" and err.strip() and "Traceback" not in err,
             "drill: no brain is one line on stderr, exit 1", err[:120])

        # spark watch: the operational-stream monitor (contract 14)
        rc, out, _ = spark("watch", "-h")
        t.ok(rc == 0 and out.startswith("spark watch -- "), "watch -h is signed", out[:40])
        rc, out, err = spark("watch", "when a 500 appears", stdin="GET /a 200 ok\nGET /x 500\n")
        t.ok(rc == 0 and out == 'A 500 error appeared: "GET /x 500"\n',
             "watch: a matching line is reported once, quoting it, newline-terminated", repr(out) + err)
        rc, out, err = spark("watch", "when a 500 appears", stdin="GET /a 200\nGET /b 204\n")
        t.ok(rc == 0 and out == "", "watch: nothing matches, nothing is said -- silence is the answer", repr(out) + err)
        rc, out, err = spark("watch", "when a 500 appears", stdin="connection error 5001 logged\n")
        t.ok(rc == 0 and out == "",
             "watch: a quote of \"error 500\" cannot ground against a window holding only 5001", repr(out) + err)
        # the watcher never watches itself: spark's own journal lines and a
        # llama-server log line are dropped before the window, and a window
        # of only those is no model call at all
        n_own = len(STATE["bodies"])
        own = ("Sep 21 19:40:37 spark spark[989563]: 654.40.690.647 W srv    operator(): unauthorized: Invalid API Key\n"
               "655.33.238.200 I slot get_availabl: id  2 | task -1 | selected slot by LCP similarity\n"
               "Sep 21 19:41:00 spark spark[989568]: 192.0.2.5 - \"POST /v1/chat/completions\" 200\n")
        rc, out, err = spark("watch", "anything that fails", stdin=own)
        t.ok(rc == 0 and out == "" and len(STATE["bodies"]) == n_own, "watch: the brain's own log lines make no window and no call", repr(out) + err)
        rc, out, err = spark("watch", "when a 500 appears", stdin=own + "GET /x 500\n")
        t.ok(rc == 0 and out == 'A 500 error appeared: "GET /x 500"\n' and len(STATE["bodies"]) == n_own + 1
             and "slot get_availabl" not in (STATE.get("last_user") or "") and "spark[989563]" not in (STATE.get("last_user") or ""),
             "watch: the own lines are gone from the window, the real line still matches", repr(out) + repr(STATE.get("last_user"))[:200])
        # a burst: 30 lines arriving at once must all be in the FIRST window.
        # readline() buffered past select's sight and starved the window to
        # one line per tick; the reader drains the fd now. The pipe is held
        # open so only the window timer (1 s via the seam) can close it.
        burst = "".join("burst line %02d\n" % i for i in range(30))
        n0 = len(STATE["bodies"])
        p = subprocess.Popen([sys.executable, SPARK, "watch", "when a 500 appears"],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True,
                             env=dict(env, SPARK_WATCH_SECS="1"))
        got = None
        try:
            p.stdin.write(burst)
            p.stdin.flush()
            deadline = time.time() + 10
            while time.time() < deadline and got is None:
                for b in STATE["bodies"][n0:]:
                    u = b["messages"][-1].get("content", "")
                    if "burst line 00" in u:
                        got = u
                        break
                time.sleep(0.1)
        finally:
            p.stdin.close()
            p.wait(timeout=10)
        t.ok(got is not None and all(("burst line %02d" % i) in got for i in range(30)),
             "watch: a 30-line burst is one window -- the reader drains what select saw",
             ("no window seen: " + p.stderr.read()[-300:]) if got is None else got[-100:])
        # a rotated token mid-run: not a transient, so the loop ends in one
        # signed line on stderr, exit 1 -- never a traceback
        STATE["auth_reject"] = True
        rc, out, err = spark("watch", "when a 500 appears", stdin="GET /x 500\n")
        STATE["auth_reject"] = False
        t.ok(rc == 1 and out == "" and err.startswith("spark watch -- ") and "Traceback" not in err,
             "watch: a 401 mid-run is one signed line, exit 1", repr(err[:120]))
        rc, out, _ = spark("watch")
        t.ok(rc == 2 and out.startswith("spark watch -- ") and "spark <words>" in out,
             "watch: no words is the usage and where a question goes, exit 2", out[:60])
        from spark import watch as watchmod
        t.ok(not watchmod._due(0, None, 100.0) and not watchmod._due(3, 99.0, 100.0)
             and watchmod._due(3, 89.0, 100.0) and watchmod._due(watchmod.WINDOW_LINES, 100.0, 100.0),
             "watch: a window is due when it is full or old enough, never when empty")

        # spark edit --watch: the live-writing companion (a mode of contract 10)
        from spark import edit as editmod
        t.ok(editmod.stanzas("one\n\ntwo\n\n\n  three  ") == ["one", "two", "three"],
             "edit --watch: the draft splits into stanzas on blank lines", str(editmod.stanzas("one\n\ntwo")))
        rc, out, err = spark("edit", "--watch", home + "/no-such-draft.md")
        t.ok(rc == 1 and "no such file" in err, "edit --watch: a missing file is one line, exit 1", err)
        draft = home + "/draft.md"
        with open(draft, "w") as f:
            f.write("The first paragraph is already written.\n")
        p = subprocess.Popen([sys.executable, SPARK, "edit", "--watch", draft],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             env=dict(env, SPARK_EDIT_WATCH_POLL="0.1"))
        try:
            time.sleep(0.4)
            with open(draft, "a") as f:
                f.write("\nA second paragraph about the gate.\n")
            time.sleep(0.6)
        finally:
            p.terminate()
        wout, werr = p.communicate(timeout=10)
        t.ok("edit --watch" in wout and len(wout.splitlines()) >= 2,
             "edit --watch: it announces the draft and comments on a saved stanza", repr(wout[:200]) + werr[:200])
        # a rotated token mid-run ends the companion the same way: one
        # signed line on stderr, exit 1 -- never a traceback
        STATE["auth_reject"] = True
        p = subprocess.Popen([sys.executable, SPARK, "edit", "--watch", draft],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             env=dict(env, SPARK_EDIT_WATCH_POLL="0.1"))
        try:
            time.sleep(0.3)
            with open(draft, "a") as f:
                f.write("\nA third paragraph, saved under a dead token.\n")
            wout, werr = p.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            p.kill()
            wout, werr = p.communicate()
        STATE["auth_reject"] = False
        t.ok(p.returncode == 1 and "spark edit --watch -- " in werr and "Traceback" not in werr,
             "edit --watch: a 401 mid-run is one signed line, exit 1", repr(werr[-160:]))

        # session.once: a loop rides out a transient brain, dies on a real fault
        from spark import session as sessmod, wire as wiremod
        _drop = wiremod.drop_cache
        wiremod.drop_cache = lambda: None
        try:
            ok1, val1 = sessmod.once(lambda: "S", lambda s: "ran:" + s)

            def _boom(kind):
                def run(_s):
                    raise wiremod.BrainError(kind, "the brain went away")
                return run
            ok2, hint2 = sessmod.once(lambda: "S", _boom("cut"))
            raised = False
            try:
                sessmod.once(lambda: "S", _boom("auth"))
            except wiremod.BrainError:
                raised = True
        finally:
            wiremod.drop_cache = _drop
        t.ok(ok1 and val1 == "ran:S" and ok2 is False and hint2 == "the brain went away" and raised,
             "session.once: success passes through, a cut is a skip, an auth fault is raised")

        # spark share: one engine for the machine's other OS users (v1.22)
        rc, out, _ = spark("share", "-h")
        t.ok(rc == 0 and out.startswith("spark share -- "), "share -h is signed", out[:40])
        rc, out, _ = spark("share")
        t.ok(rc == 0 and "SITE_SHARE=no" in out, "share: status shows not-shared by default", out[:80])
        from spark import site as sitemod, config as configmod
        t.ok(isinstance(sitemod.no_share(), str) and isinstance(sitemod.share_facts(configmod.load()), list),
             "share: no_share() and share_facts() answer on this OS without a crash")
        # the join side: a shared-engine token is recorded for a client, not minted
        os.makedirs(home + "/.config-share/spark", exist_ok=True)
        sharetok = home + "/shared-token"
        with open(sharetok, "w") as f:
            f.write("SHAREDSECRET\n")
        rc, out, err = spark("client", "http://127.0.0.1:8080", extra={
            "XDG_CONFIG_HOME": home + "/.config-share", "XDG_STATE_HOME": home + "/.local/state-share",
            "SPARK_SHARE_TOKEN": sharetok, "SPARK_NO_APPLY": "1"})
        try:
            sparkenv = open(home + "/.config-share/spark/spark.env").read()
        except OSError:
            sparkenv = ""
        t.ok(rc == 0 and ("SPARK_API_KEY_FILE=" + sharetok) in sparkenv,
             "spark client: a readable shared-engine token is recorded, not a token of its own", repr(sparkenv[-160:]) + err)
        # a client on a shared-engine box makes NO root step and never removes
        # the owner's token: bootstrap's share section skips for a client
        ownertok = home + "/owner-token"
        with open(ownertok, "w") as f:
            f.write("OWNERSECRET\n")
        benv = dict(env, SITE_AI_MODEL="none", SITE_PEER_AI_URL="http://127.0.0.1:8080", SPARK_SHARE_TOKEN=ownertok)
        p = subprocess.run(["sh", os.path.join(REPO, "bootstrap.sh"), "--dry-run"],
                           capture_output=True, text=True, env=benv, timeout=60)
        lines = p.stdout.splitlines()
        skipped = any(ln.startswith("skip") and "share" in ln for ln in lines)
        removes = any(ln.startswith("would") and "share" in ln and "remove" in ln for ln in lines)
        t.ok(skipped and not removes and os.path.exists(ownertok),
             "share: a client skips the share section -- no root, the owner's token untouched",
             "\n".join(ln for ln in lines if "share" in ln)[-200:] + p.stderr[-120:])

        # the Terminal.app profile carries the keys micro needs
        from spark import theme as thememod
        fixture_pal = dict(("THEME_ANSI_%d" % i, "#%02x%02x%02x" % (i, i, i)) for i in range(16))
        fixture_pal.update({"THEME_BG": "#111111", "THEME_FG": "#eeeeee", "THEME_ACCENT": "#ff0000", "THEME_MUTED": "#888888"})
        pd = thememod.profile_dict("spark-fixture", fixture_pal, "Menlo", 13)
        t.ok(pd.get("useOptionAsMetaKey") is True and pd["keyMapBoundKeys"]["$F701"] == "\x1b[1;2B" and len(pd["keyMapBoundKeys"]) == 8,
             "profile: Option is Meta and Shift/Ctrl arrows are bound", json.dumps(pd.get("keyMapBoundKeys")))

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
        t.ok("spark's own commands" in esys and "spark quiet start|login|boot|audio on|off" in esys and "--reveal" in esys
             and "spark shell on|off" not in esys,
             "ask knows spark's own commands (the machine can explain itself)", esys[:200])
        t.ok("spark's own commands" in system1, "the line prompt knows spark's own commands too", system1[:200])
        from spark import persona as _persona
        _know = _persona.KNOW_SHELL + _persona.KNOW_CHAT
        t.ok("spark-shell" not in _know and "shell layer" not in _know.lower() and "spark bar" in _know,
             "KNOW_SHELL and KNOW_CHAT name spark's own verbs (the bar line) and no shell layer", _know[-160:])
        # chat sheds the shell costume: one machine line + identity + the mode
        spark("chat", "hello", extra={"SPARK_BASE_URL": url2})
        csys = req["body"]["messages"][0]["content"]
        t.ok(req["body"].get("model") == "ember", "chat names the ember role", csys[:100])
        t.ok(csys.startswith("You are on ") and "Call yourself Fixture." in csys and "This is a conversation" in csys,
             "chat: one machine line + identity + the chat mode", csys[:200])
        t.ok("Preferred when installed" not in csys and "Flags that exist" not in csys and "Package manager" not in csys
             and "System tools" not in csys, "chat sheds the shell costume", csys[:200])
        # a Linux session with no display is told so (a Void console once got
        # Alacritty's config for a console font); a display, or macOS, is not
        import platform as _platform
        _pers_env = dict(os.environ)
        try:
            for k in ("DISPLAY", "WAYLAND_DISPLAY"):
                os.environ.pop(k, None)
            _plain = _persona.machine_line(_config.load(), local=True)
            _page = _persona.machine_line(_config.load())
            os.environ["DISPLAY"] = ":0"
            _shown = _persona.machine_line(_config.load(), local=True)
        finally:
            os.environ.clear()
            os.environ.update(_pers_env)
        _linux = _platform.system() == "Linux"
        t.ok(("no graphical display" in _plain) == _linux and "no graphical display" not in _shown
             and "no graphical display" not in _page,
             "machine line: a Linux session with no display says so; a display, or the page's server, does not", _plain)
        t.ok("no markdown marks" in csys, "chat rules out markdown for the terminal", csys[-200:])
        t.ok("spark's own commands" in csys and "The look: spark theme NAME" in csys,
             "chat knows spark's own commands, grouped with meanings", csys[:200])
        spark("chat", "hello again", extra={"SPARK_BASE_URL": url2})
        t.ok(req["body"]["messages"][0]["content"] == csys, "the chat system message is byte-identical across requests")
        spark("tell", "me", "again", extra={"SPARK_BASE_URL": url2, "SPARK_MEMORY": "off"})
        sent = json.dumps(req.get("body", {}))
        t.ok("remembered" not in req["body"]["messages"][0]["content"] and home not in sent, "SPARK_MEMORY=off sends no facts", sent[:200])
        rc, out, _ = spark("memory", "forget", "1")
        t.ok(rc == 0 and "forgot" in out, "spark memory forget 1", out)
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
        rc, out, _ = spark("bar")       # a status bar runs it without a tty
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
        rc, out, _ = spark("memory", "add", "-h")
        t.ok(rc == 0 and out.startswith("spark memory -- "), "remember -h is help, not a fact", out)
        rc, out, _ = spark("memory", "forget", "-h")
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

        # ---- v1.36: what leaves is counted by destination (out_bytes and
        # dest on every turn; spark stats --sends; the sends row), the
        # FORGE's gates probed from the wire (wire.probe_gates,
        # tests/forge_probe.py, the hardening row), and spark do's harness
        # banner ------------------------------------------------------------
        from spark import wire as _wire
        t.ok(_wire.dest_of("http://127.0.0.1:8080") == "local" and _wire.dest_of("http://localhost:8081/") == "local"
             and _wire.dest_of("http://192.0.2.7:8081") == "192.0.2.7:8081" and _wire.dest_of("http://box.local") == "box.local",
             "wire.dest_of: loopback is local, anything else host:port")
        spark("history", "clear")
        spark("line", stdin="?biggest dir here")          # the streamed JSON (the line)
        spark("count?")                                   # the streamed text (chat_stream)
        turns = [json.loads(l) for f in os.listdir(home + "/.local/state/spark/turns")
                 for l in open(home + "/.local/state/spark/turns/" + f) if l.strip()]
        t.ok(len(turns) >= 2 and all(isinstance(x.get("out_bytes"), int) and x["out_bytes"] > 100 and x.get("dest") == "local" for x in turns),
             "every turn records its bytes out and its destination (local: the stub is loopback), both shapes",
             [(x.get("mode"), x.get("out_bytes"), x.get("dest")) for x in turns])
        total = sum(x["out_bytes"] for x in turns)
        today = time.strftime("%Y-%m-%d")
        rc, out, _ = spark("stats", "--sends", "--porcelain")
        t.ok(rc == 0 and [l.split("\t") for l in out.splitlines()] == [[today, "local", str(total), str(len(turns))]],
             "stats --sends --porcelain: day, destination, bytes, turns -- the records' own sum", out)
        rc, out, _ = spark("stats", "--sends")
        t.ok(rc == 0 and "sends" in out and "last 7 days" in out and today in out and "local" in out and "%.1f" % (total / 1000.0) in out,
             "stats --sends: the table at the terminal, in kB", out)
        rc, out, _ = spark("check", "sends", "--porcelain")
        t.ok(rc == 0 and "\tok\tsends\t%.1f kB to local today\t" % (total / 1000.0) in out,
             "check sends: today's bytes all went to local -- ok", out)
        with open(home + "/.local/state/spark/turns/" + today + ".jsonl", "a") as f:
            f.write(json.dumps({"ts": today + " 12:00:00", "kind": "answer", "mode": "chat", "ms": 5,
                                "out_bytes": 4000, "dest": "203.0.113.9:8081"}) + "\n")
        rc, out, _ = spark("check", "sends", "--porcelain")
        t.ok(rc == 0 and "\twarn\tsends\t4.0 kB went to 203.0.113.9:8081 today, not the address you configured\t" in out,
             "check sends: bytes to a host nothing here names -- warn, naming the host", out)
        rc, out, _ = spark("check", "hardening", "--porcelain")
        t.ok(rc == 0 and "\tna\thardening\t" in out, "check hardening: no FORGE served here and no peer -- na", out)
        spark("history", "clear")

        class Hardened(BaseHTTPRequestHandler):
            """A server that keeps contract 9's gates and nothing more:
            what probe_gates must call held, every one."""
            HEAD = {"Content-Security-Policy": "default-src 'self'", "X-Frame-Options": "DENY",
                    "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff"}

            def log_message(self, *a):
                pass

            def _reply(self, code, body=b"{}", extra=None):
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/api/health":
                    return self._reply(200, b'{"status":"ok","forge":true,"upstream":"ok"}')
                if self.path == "/":
                    return self._reply(200, b"<html></html>", self.HEAD)
                self._reply(401, b'{"error":{"kind":"auth"}}')

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                if self.path == "/api/login":
                    return self._reply(403 if self.headers.get("X-Spark") != "1" else 200)
                self._reply(200 if (self.headers.get("Authorization") or "").startswith("Bearer ") else 401)
        hs = HTTPServer(("127.0.0.1", 0), Hardened)
        threading.Thread(target=hs.serve_forever, daemon=True).start()
        hurl = "http://127.0.0.1:%d" % hs.server_address[1]
        gates = _wire.probe_gates(hurl, timeout=5)
        t.ok([g[0] for g in gates] == list(_wire.GATES) and all(g[1] for g in gates),
             "wire.probe_gates: a hardened FORGE holds all %d gates, in GATES order" % len(_wire.GATES), gates)
        # the hardening row against it: ok naming the count and the host,
        # then the same answer from its hour-long cache
        with open(home + "/.local/state/spark/forge-url", "w") as f:
            f.write(hurl + "\n")
        rc, out, _ = spark("check", "hardening", "--porcelain", "--fresh")
        rc2, out2, _ = spark("check", "hardening", "--porcelain")
        os.remove(home + "/.local/state/spark/forge-url")
        want = "\tok\thardening\t%d of %d gates hold at %s\t" % (len(_wire.GATES), len(_wire.GATES), hurl.split("//")[-1])
        t.ok(rc == 0 and want in out and rc2 == 0 and want in out2,
             "check hardening: the served FORGE holds every gate -- ok, fresh and from the cache", out + out2)
        hs.shutdown()
        gates = _wire.probe_gates(url, timeout=5)
        t.ok(len(gates) == len(_wire.GATES) and not gates[0][1] and "not the page's server" in gates[0][2]
             and not any(g[1] for g in gates[1:7]) and gates[7][1],
             "wire.probe_gates: the stub llama-server is not the page's server -- only the bearer-only gate holds, each miss named", gates)
        p = subprocess.run([sys.executable, os.path.join(REPO, "tests", "forge_probe.py"), url],
                           capture_output=True, text=True, timeout=60)
        plines = p.stdout.splitlines()
        t.ok(p.returncode == 1 and len(plines) == len(_wire.GATES) and all(l.startswith(("  ok   ", "  FAIL ")) for l in plines)
             and any(l.startswith("  FAIL ") for l in plines) and any(l.startswith("  ok   ") for l in plines),
             "tests/forge_probe.py URL: one line per gate, exit 1 when any does not hold", p.stdout + p.stderr)
        rc, out, err = spark("do", "say", "hello", stdin="\n", extra={"SPARK_DO_STDIN": "1"}, cwd=work)
        t.ok(rc == 0 and "STEP-ONE" in out
             and err.count("spark do: confirmations come from stdin (SPARK_DO_STDIN) -- a harness, not a person") == 1
             and "harness" not in out,
             "spark do: SPARK_DO_STDIN=1 says so once on stderr -- a harness, not a person; stdout stays the run", out + err)
        # ---- end of the v1.36 block ------------------------------------------

        # spark do: one confirmed command at a time (SPARK_DO_STDIN=1 reads the confirmations from stdin)
        hook = {"SPARK_DO_STDIN": "1"}
        spark("history", "clear")
        rc, out, err = spark("do", "say", "hello", stdin="\n", extra=hook, cwd=work)
        t.ok(rc == 0 and "STEP-ONE" in out and "done  all done" in out, "spark do: proposes, Enter runs it, the output ends it", out + err)
        t.ok("1  echo STEP-ONE   say hello" in out and "Enter runs it" in out, "spark do: the step line and the prompt", out)
        names = os.listdir(threads)
        lines = read_thread(home, threads + "/" + names[0]) if len(names) == 1 else []
        t.ok(len(lines) == 4 and [l["role"] for l in lines] == ["user", "assistant"] * 2 and "Output of `echo STEP-ONE` (exit 0)" in lines[2]["text"], "spark do: one thread, goal / step / output / done", lines)
        turns = [json.loads(l) for f in os.listdir(home + "/.local/state/spark/turns") for l in open(home + "/.local/state/spark/turns/" + f) if l.strip()]
        dos = [x for x in turns if x.get("mode") == "do"]
        t.ok(len(dos) == 2 and dos[0]["kind"] == "cmd" and dos[0]["rc"] == 0 and dos[1]["kind"] == "done", "spark do: the turn log has the step with its rc, then the done", dos)
        t.ok(all(k not in x for x in turns for k in ("line", "command", "hint", "answer", "cwd", "context")),
             "turns are numbers only: no free text survives the strip", [sorted(x) for x in turns[:3]])
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
        # the record is what ran: the edited command lands on the thread
        # the moment it ran, naming the proposal it replaced
        newest = max(os.listdir(threads), key=lambda f: os.path.getmtime(os.path.join(threads, f)))
        lines = read_thread(home, os.path.join(threads, newest))
        t.ok(len(lines) == 4 and lines[2]["role"] == "user"
             and lines[2]["text"].startswith("Output of `echo EDITED` (exit 0; edited from `echo again`):"),
             "spark do: the thread records the command that ran, `edited from` the proposal", lines)
        rc, out, err = spark("do", "forever", stdin="s\nq\n", extra=dict(hook, SPARK_BASE_URL=url2), cwd=work)
        t.ok("skipped this step (" in req["body"]["messages"][-1]["content"] and "Do not propose it again" in req["body"]["messages"][-1]["content"],
             "spark do: s tells the model the step was skipped, naming it", out + err)
        # the stub proposes the same step forever: after the skip it is
        # re-asked once, silently, then the run stops -- the user never
        # answers the same skipped step twice
        t.ok(rc == 1 and "the same step again after a skip -- stopped" in out and out.count("Enter runs it") == 1,
             "spark do: a skipped step that comes back is re-asked once, then the run stops", out + err)
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
        rc, out, err = spark("do", "goodsum", stdin="\n\n", extra=hook, cwd=work)
        t.ok(rc == 0 and "unchecked" not in out and "done  Total: 26" in out, "spark do: a number an output backs passes clean", out + err)
        t.ok(out.count("Enter runs it") == 2 and "proof: test -d ." in out and "proof -> ok" in out
             and out.index("proof: test -d .") < out.index("proof -> ok"),
             "spark do: the proof is asked for like a step (Enter), then runs and shows its result", out)
        # the proof's output never rides the next request: only its exit
        # code does -- and the step's feedback lands on the thread even
        # when the run stops right there (q at the proof)
        open(work + "/secret.txt", "w").write("SECRET-PROOF-MARK\n")
        rc, out, err = spark("do", "proofleak", stdin="\n\n", extra=dict(hook, SPARK_BASE_URL=url2), cwd=work)
        _last = req["body"]["messages"][-1]["content"]
        t.ok(rc == 0 and "proof -> exit 1" in out and "SECRET-PROOF-MARK" in out
             and "Proof `head secret.txt /nonexistent` exited 1." in _last
             and "SECRET-PROOF-MARK" not in json.dumps(req["body"]),
             "spark do: a failed proof's exit code goes back, its output never does", _last[-200:] + out + err)
        rc, out, err = spark("do", "goodsum", stdin="\nq\n", extra=hook, cwd=work)
        newest = max(os.listdir(threads), key=lambda f: os.path.getmtime(os.path.join(threads, f)))
        lines = read_thread(home, os.path.join(threads, newest))
        t.ok(rc == 0 and "stopped after 1 step" in out and "proof ->" not in out
             and len(lines) == 3 and lines[2]["role"] == "user"
             and lines[2]["text"].startswith("Output of `echo 26` (exit 0):") and "Proof" not in lines[2]["text"],
             "spark do: q at the proof skips it, and the last step is on the thread anyway", str(lines) + out)
        # a control character in the model's command: refused whole, a done
        os.mkdir(work + "/junk2")
        rc, out, err = spark("do", "ctrlchar", stdin="\n", extra=hook, cwd=work)
        t.ok(rc == 0 and "done  the model's command carried control characters -- refused" in out
             and "Enter runs it" not in out and "\x1b" not in out and os.path.isdir(work + "/junk2"),
             "spark do: a command carrying an escape is refused as done; nothing ran, nothing printed raw", repr(out) + err)
        # the leash on a proof: rc 124 with the tail so far, the group killed
        from spark import do as _do
        _t0 = time.time()
        _rc, _tail = _do.run("echo hi; sleep 20", "sh", timeout=0.5)
        t.ok(_rc == 124 and "hi" in _tail and time.time() - _t0 < 5,
             "do.run(timeout=): a proof that hangs is killed, rc 124, the tail kept", (_rc, _tail))
        # ... and the leash holds when a process left the group (setsid)
        # still holds the pipe: reading stops, the step is rc 124
        _t0 = time.time()
        _rc, _tail = _do.run("%s -c 'import os, time; os.setsid(); time.sleep(21.5)' & echo hi; sleep 9"
                             % sys.executable, "sh", timeout=0.5)
        subprocess.run(["pkill", "-f", "time.sleep(21.5)"], capture_output=True)
        t.ok(_rc == 124 and "hi" in _tail and time.time() - _t0 < 5,
             "do.run(timeout=): a setsid grandchild holding the pipe cannot keep a step past its leash",
             (_rc, _tail, time.time() - _t0))
        # the head-word guard in do: never offered, fed back, the loop goes on
        rc, out, err = spark("do", "missdo", "scan", stdin="", extra=hook, cwd=work)
        t.ok(rc == 0 and "frobnicate: not on this machine" in out and "gave up" in out and "Enter runs it" not in out,
             "spark do: a step naming a missing binary is not offered to run", out + err)
        rc, out, err = spark("do", "missdo", "scan", stdin="", extra=dict(hook, SPARK_BASE_URL=url2), cwd=work)
        t.ok(rc == 0 and "frobnicate is not installed on this machine" in req["body"]["messages"][-1]["content"],
             "spark do: the model hears the missing binary as feedback", req["body"]["messages"][-1]["content"][:120])

        # ---- v1.47: do, measured, bounded, held; the OS documents its tools
        from spark import reveal as _reveal

        def do_turns():
            tdir = home + "/.local/state/spark/turns"
            return [json.loads(l) for f in sorted(os.listdir(tdir)) for l in open(os.path.join(tdir, f)) if l.strip()
                    and json.loads(l).get("mode") == "do"]
        # every proposal is a turn with the server's timings: the prompt
        # cache's hits are measured, and the model is the stem that answered
        t0 = len(do_turns())
        n0 = len(STATE["bodies"])
        rc, out, err = spark("do", "say", "hello", stdin="\n", extra=hook, cwd=work)
        new = do_turns()[t0:]
        t.ok(rc == 0 and [x["kind"] for x in new] == ["cmd", "done"]
             and all(x.get("pp_n") == 40 and x.get("cache_n") == 30 and x.get("tg_tps") for x in new)
             and all(x.get("model") == "stub-ember-q4" for x in new),
             "spark do: every proposal is a turn with pp_n/cache_n/tg_tps, the ember stem that answered", new)
        t0 = len(do_turns())
        rc, out, err = spark("do", "forever", stdin="s\nq\n", extra=hook, cwd=work)
        spark("do", "forever", stdin="q\n", extra=hook, cwd=work)
        new = do_turns()[t0:]
        t.ok([x["kind"] for x in new] == ["skipped", "reasked", "stopped", "quit"]
             and all(x.get("pp_n") == 40 and x.get("cache_n") == 30 for x in new),
             "spark do: a skip, the silent re-ask, the stop and a quit are turns too, measured", [x.get("kind") for x in new])
        rc, out, _ = spark("stats", "--porcelain")
        t.ok(re.search(r"^mode_do\tturns=\d+ cache_pct=43 ", out, re.M) is not None,
             "spark stats: do's cache hits are real (30 of 70 prompt tokens: 43%)", out)
        # system message and goal: byte-identical at every step (the prefix a cache hits)
        n0 = len(STATE["bodies"])
        rc, out, err = spark("do", "forever", stdin="\n\n\nq\n", extra=hook, cwd=work)
        bodies = [b for b in STATE["bodies"][n0:] if is_do(b["messages"])]
        t.ok(len(bodies) == 4 and all(b["messages"][0] == bodies[0]["messages"][0] and b["messages"][1] == bodies[0]["messages"][1]
                                      for b in bodies)
             and bodies[0]["messages"][1]["content"] == "[cwd %s]\nforever" % os.path.realpath(work),
             "spark do: the system message and message 0 (the goal) are byte-identical across steps",
             [len(b["messages"]) for b in bodies])
        # the budget: 4 kB a step into a 4096-token context -- the oldest
        # outputs shortened first, the goal kept, the roles alternating
        n0 = len(STATE["bodies"])
        rc, out, err = spark("do", "bigout", "goal", stdin="\n" * 9, extra=dict(hook, SPARK_CTX="4096"), cwd=work)
        bodies = [b for b in STATE["bodies"][n0:] if is_do(b["messages"])]
        cap = int((4096 - _do.DO_MAX_TOKENS) * _reveal.CHARS_PER_TOKEN * _do.CTX_SHARE)
        sizes = [sum(len(m["content"]) for m in b["messages"]) for b in bodies]
        last = bodies[-1]["messages"] if bodies else []
        t.ok(rc == 1 and len(bodies) == 8 and max(sizes) <= cap and sum(len(m["content"]) for m in last[1:]) > 4000,
             "spark do: a run of 4 kB outputs stays under the budget of the served context", (sizes, cap))
        t.ok(all(b["messages"][1]["content"] == "[cwd %s]\nbigout goal" % os.path.realpath(work) for b in bodies)
             and "(output trimmed, exit 0)" in [m["content"] for m in last]
             and [m["role"] for m in last[1:]] == ["user", "assistant"] * ((len(last) - 1) // 2) + ["user"] * ((len(last) - 1) % 2),
             "spark do: the goal is kept, the oldest outputs become (output trimmed, exit N), the roles alternate",
             [m["content"][:40] for m in last])
        _fit = _do.fit([{"role": "user", "content": "G" * 50}] + [{"role": r, "content": c} for r, c in (
            ("assistant", "`a` -- x"), ("user", "Output of `a` (exit 3):\n" + "o" * 500),
            ("assistant", "`b` -- y"), ("user", "Output of `b` (exit 0; edited from `c`):\n" + "p" * 500),
            ("assistant", "`d` -- z"), ("user", "Output of `d` (exit 1):\n" + "q" * 500))], 640)
        t.ok([m["content"][:25] for m in _fit] == ["G" * 25, "`b` -- y", "(output trimmed, exit 0)", "`d` -- z",
                                                   "Output of `d` (exit 1):\nq"],
             "do.fit: outputs trimmed oldest first with their exit code, then the oldest exchange dropped; goal and newest kept",
             [m["content"][:30] for m in _fit])
        # a step's output passes text.hold_secrets before it is fed back
        _gh = "ghp_Z9y8X7w6V5u4T3s2R1q0P9o8N7m6L5k4J3i2"  # spark:allow-secret
        with open(work + "/creds.txt", "w") as f:
            f.write("deploy token " + _gh + "\n")  # spark:allow-secret
        t0 = len(do_turns())
        rc, out, err = spark("do", "leakstep", stdin="\n", extra=hook, cwd=work)
        sent = json.dumps(STATE["bodies"][-1])
        newest = max(os.listdir(threads), key=lambda f: os.path.getmtime(os.path.join(threads, f)))
        kept = json.dumps(read_thread(home, os.path.join(threads, newest)))
        cmdturn = [x for x in do_turns()[t0:] if x.get("kind") == "cmd"]
        t.ok(rc == 0 and _gh in out and _gh not in sent and "deploy token [held]" in sent and _gh not in kept
             and "held back 1 span that looks like a secret (a GitHub token)" in err
             and cmdturn and cmdturn[0].get("held") == 1,
             "spark do: a secret a step printed is held before the model or the thread sees it; held=1 on the turn",
             err + sent[-300:])
        # the OS documents its tools: a step refused for an option brings
        # back its own man page's lines about it -- man as argv, the tool
        # never run for it, the pager variables dropped, MANWIDTH=80
        mbin = home + "/mbin"
        os.makedirs(mbin, exist_ok=True)
        with open(mbin + "/fakeflag", "w") as f:
            f.write("#!/bin/sh\necho x >> \"$HOME/fakeflag-ran\"\n"
                    "echo \"fakeflag: unrecognized option '$1'\"\n"
                    "[ \"$1\" = --ok ] && exit 0\nexit 2\n")
        with open(mbin + "/man", "w") as f:
            f.write("#!/bin/sh\nprintf '%s\\n' \"$*\" > \"$HOME/man-argv\"\n"
                    "printf 'MANWIDTH=%s MANPAGER=%s PAGER=%s MANOPT=%s\\n' \"$MANWIDTH\" \"${MANPAGER-unset}\" "
                    "\"${PAGER-unset}\" \"${MANOPT-unset}\" > \"$HOME/man-env\"\n"
                    "printf 'FAKEFLAG(1)\\n\\nS\\bSY\\bYN\\bNO\\bOP\\bPS\\bSI\\bIS\\bS\\n"
                    "     fakeflag [--frobnicate] [-v]\\n\\nOPTIONS\\n"
                    "     -\\b--\\b-f\\bfr\\bro\\bob\\bb  _\\bnever an option here\\n     -v      verbose\\n'\n")
        for x in ("fakeflag", "man"):
            os.chmod(mbin + "/" + x, 0o755)
        menv = dict(hook, PATH=mbin + ":" + env["PATH"], MANPAGER="false", PAGER="false", MANOPT="-X")
        for x in ("man-argv", "fakeflag-ran"):
            if os.path.exists(home + "/" + x):
                os.remove(home + "/" + x)
        rc, out, err = spark("do", "badflag", stdin="\n", extra=menv, cwd=work)
        umsg = STATE["bodies"][-1]["messages"][-1]["content"]
        t.ok(rc == 0 and "From man fakeflag:\nOPTIONS\n     --frob  never an option here\n     -v      verbose" in umsg
             and "\x08" not in umsg and umsg.index("From man") > umsg.index("unrecognized option")
             and "From man fakeflag: 3 lines go back with the output" in out,
             "spark do: a step refused for an option -- the next request carries its man page's lines about it", repr(umsg[-300:]) + out)
        t.ok(open(home + "/man-argv").read() == "-P cat fakeflag\n"
             and open(home + "/man-env").read() == "MANWIDTH=80 MANPAGER=unset PAGER=unset MANOPT=unset\n"
             and open(home + "/fakeflag-ran").read() == "x\n",
             "spark do: man runs as argv (-P cat HEAD), pager variables dropped, MANWIDTH=80; the tool ran once, as the step",
             open(home + "/man-env").read() if os.path.exists(home + "/man-env") else "no man-env")
        os.remove(home + "/man-argv")
        rc, out, err = spark("do", "goodflag", stdin="\n", extra=menv, cwd=work)
        umsg = STATE["bodies"][-1]["messages"][-1]["content"]
        t.ok(rc == 0 and "unrecognized option" in umsg and "From man" not in umsg and not os.path.exists(home + "/man-argv"),
             "spark do: the same words from a step that exited 0 read no man page", umsg[-200:])
        t.ok(_do.man_excerpt("fakeflag --frob", 2, "no complaint here") == ""
             and _do.man_excerpt("/bin/fakeflag --frob", 2, "unrecognized option '--frob'") == ""
             and _do.man_excerpt("no-such-tool-here --frob", 2, "unrecognized option '--frob'") == "",
             "do.man_excerpt: nothing without the error words, for a path, or for a tool `which` does not find")
        _sends = [(k, v) for k, v in _pers.SENDS if "man page" in v]
        t.ok(len(_sends) == 1 and _sends[0][0] == "do" and "%.1f kB" % (_do.MAN_MAX / 1000.0) in _sends[0][1]
             and any(k == "do" and "held back" in v for k, v in _pers.SENDS),
             "persona.SENDS: do's man-page row names its cap (do.MAN_MAX), and do's output row the hold", _sends)

        # ---- v1.47: the sandbox, the review, detach, porcelain (contract 15)
        # a checksum tool's line keeps its digest (do.CHECKSUM_LINE, the
        # step's argv[0] one of do.CHECKSUM_TOOLS); a real token on the same
        # output is still held, and `cat` printing the same lines proves
        # nothing: held
        _dig = hashlib.sha256(b"spark").hexdigest()
        with open(work + "/sums.txt", "w") as f:
            f.write("%s  spark.tar.gz\n%s *spark.bin\ndeploy token %s\n" % (_dig, _dig, _gh))  # spark:allow-secret
        with open(mbin + "/sha256sum", "w") as f:
            f.write("#!/bin/sh\ncat \"$1\"\n")      # prints the lines above, as a checksum tool's
        os.chmod(mbin + "/sha256sum", 0o755)
        rc, out, err = spark("do", "sumstep", stdin="\n", extra=menv, cwd=work)
        umsg = STATE["bodies"][-1]["messages"][-1]["content"]
        t.ok(rc == 0 and ("%s  spark.tar.gz" % _dig) in umsg and ("%s *spark.bin" % _dig) in umsg
             and _gh not in umsg and "deploy token [held]" in umsg and "held back 1 span" in err,
             "do.CHECKSUM_LINE: a sha256sum line keeps its digest; a token on the same output is still held",
             umsg[-300:] + err)
        rc, out, err = spark("do", "catsum", stdin="\n", extra=hook, cwd=work)
        umsg = STATE["bodies"][-1]["messages"][-1]["content"]
        t.ok(rc == 0 and _dig not in umsg and "[held]  spark.tar.gz" in umsg and "held back 3 spans" in err,
             "do.hold: the same lines from `cat` are held -- the exemption is the checksum tool's alone",
             umsg[-300:] + err)
        t.ok(_do.hold(_dig + "  x\n", "cat f")[1] == 1 and _do.hold(_dig + "  x\n", "sha256sum x") == (_dig + "  x\n", 0, [])
             and _do.hold(_dig + "  x\n", "/usr/bin/shasum -a 256 x")[1] == 0
             and _do.hold(_dig + "\n", "sha256sum x")[1] == 1 and _do.hold("x " + _dig + "  f\n", "sha256sum x")[1] == 1
             and _do.hold("f" * 65 + "  x\n", "sha256sum x")[1] == 1
             and _do.hold(_dig + "  x\n", "cat f | sha256sum")[1] == 1,
             "do.hold(text, command): a <hex>  x line from cat is held, from a checksum tool kept -- only that "
             "shape, only a digest's length, only argv[0]")
        # spark's own secrets are held by their exact contents, whatever
        # their shape (do.own_secrets): here the shared engine's token file
        _own = "zq81-vk27-mm4p-x0c3-lw9e-hh5t"
        with open(home + "/share-token", "w") as f:
            f.write(_own + "\n")
        with open(work + "/tok.txt", "w") as f:
            f.write("the engine answers to " + _own + "\n")
        rc, out, err = spark("do", "tokstep", stdin="\n", extra=dict(hook, SPARK_SHARE_TOKEN=home + "/share-token"),
                             cwd=work)
        sent = json.dumps(STATE["bodies"][-1])
        t.ok(rc == 0 and _own not in sent and "answers to [held]" in sent and "(a spark token)" in err,
             "do.hold: a step that prints one of spark's own tokens (a named file's exact contents) -- held",
             err + sent[-200:])

        def events(out):
            """stdout of --porcelain, one JSON object a line -- None when
            any line is not one (stdout carries nothing else)."""
            try:
                evs = [json.loads(l) for l in out.splitlines()]
            except ValueError:
                return None
            return evs if all(isinstance(e, dict) and "ev" in e for e in evs) else None

        def kinds(evs):
            return [e["ev"] for e in evs or []]
        # porcelain, plain: a step waits for run; its proof is a step of its own
        rc, out, err = spark("do", "--porcelain", "goodsum", stdin="run\nrun\n", cwd=work)
        evs = events(out)
        t.ok(rc == 0 and kinds(evs) == ["start", "note", "step", "output", "rc", "step", "rc", "end"]
             and evs[0] == {"ev": "start", "thread": evs[0]["thread"], "sandbox": False, "run": None}
             and evs[2] == {"ev": "step", "n": 1, "command": "echo 26", "hint": "count things", "danger": False,
                            "proof": "test -d ."}
             and evs[3] == {"ev": "output", "n": 1, "text": "26\n"} and evs[4] == {"ev": "rc", "n": 1, "rc": 0}
             and evs[5] == {"ev": "step", "n": 2, "command": "test -d .", "hint": "proof of step 1",
                            "danger": False, "proof": None}
             and evs[7] == {"ev": "end", "reason": "done", "hint": "Total: 26", "rc": 0},
             "spark do --porcelain: start, the step, its output and rc, the proof as its own step, end (contract 15)",
             out + err)
        t.ok(err.count(_do.PORCELAIN_BANNER) == 1 and "driving" not in err,
             "spark do --porcelain: a stderr banner says a program drives it; stdout is only JSON lines", err)
        os.makedirs(work + "/junk", exist_ok=True)
        rc, out, err = spark("do", "--porcelain", "rm-plain", "junk", stdin="run\n", cwd=work)
        evs = events(out)
        t.ok(rc == 0 and kinds(evs) == ["start", "note", "step", "note", "end"] and evs[2]["danger"] is True
             and "refused over --porcelain" in evs[3]["text"] and evs[4]["reason"] == "done"
             and os.path.isdir(work + "/junk") and "skipped this step" in STATE["last_user"],
             "spark do --porcelain: a danger step is refused without waiting -- no yes word; the model hears skipped",
             out + err)
        rc, out, err = spark("do", "--porcelain", "forever", stdin="edit echo EDITED\nquit\n", cwd=work)
        evs = events(out)
        t.ok(rc == 0 and kinds(evs) == ["start", "note", "step", "note", "output", "rc", "step", "end"]
             and evs[4]["text"] == "EDITED\n" and evs[7]["reason"] == "quit",
             "spark do --porcelain: edit <command> runs the edit, quit ends the run", out + err)
        rc, out, err = spark("do", "--porcelain", "say", "hello", stdin="skip\n", cwd=work)
        evs = events(out)
        t.ok(rc == 0 and kinds(evs) == ["start", "note", "step", "end"] and "skipped this step" in STATE["last_user"],
             "spark do --porcelain: skip -- the model hears it, the run goes on", out + err)
        rc, out, err = spark("do", "--porcelain", "forever", stdin="", cwd=work)
        evs = events(out)
        t.ok(rc == 0 and kinds(evs) == ["start", "note", "step", "end"] and evs[-1]["reason"] == "quit",
             "spark do --porcelain: EOF while a step waits is quit", out + err)
        rc, out, err = spark("do", "--porcelain", "--", "-la", "help", stdin="", cwd=work)
        t.ok(events(out) is not None and STATE["bodies"][-1]["messages"][1]["content"].endswith("]\n-la help"),
             "spark do --: the words after it are the goal, a leading - and help included", out + err)
        rc, out, err = spark("do", "--", "help", stdin="q\n", extra=hook, cwd=work)
        t.ok(rc == 0 and "driving with" in out and not out.startswith("spark do --"),
             "spark do -- help: help after -- is a goal, not the usage", out)
        rc, out, _ = spark("do", "--sandbx", "fix", "it", cwd=work)
        t.ok(rc == 2 and out.startswith("spark do -- no option --sandbx:"),
             "spark do: an option it does not take is refused, signed, exit 2", out)
        rc, out, _ = spark("do", "--detach", "x", cwd=work)
        rc2, out2, _ = spark("do", "--sandbox", "--detach", "--porcelain", "x", cwd=work)
        t.ok(rc == 2 and "--detach runs sandboxed only" in out and rc2 == 2 and "do not mix" in out2,
             "spark do --detach: sandboxed only, and never with --porcelain", out + out2)
        # over --porcelain every refusal before the run is ONE end event
        # (reason refused, rc 2) and nothing else on stdout
        for _args, _why in ((("--bogus", "x"), "no option --bogus"), ((), "no goal"),
                            (("--review",), "--review is not a run"), (("--sandbox", "--detach", "x"), "do not mix"),
                            (("x" * (_do.DO_GOAL_MAX + 1),), "a goal is at most 8 kB")):
            rc, out, err = spark("do", "--porcelain", *_args, cwd=work)
            evs = events(out)
            t.ok(rc == 2 and evs is not None and len(evs) == 1 and evs[0]["ev"] == "end"
                 and evs[0]["reason"] == "refused" and evs[0]["rc"] == 2 and _why in evs[0]["hint"],
                 "spark do --porcelain %s: one end event, reason refused, rc 2" % " ".join(_args)[:30], out + err)
        rc, out, err = spark("do", "x" * (_do.DO_GOAL_MAX + 1), stdin="q\n", extra=hook, cwd=work)
        t.ok(rc == 2 and out == "spark do -- a goal is at most 8 kB -- this one is 9 kB\n",
             "spark do: a goal over do.DO_GOAL_MAX is refused in one signed line", out + err)
        rc, out, err = spark("do", "-la", "x", cwd=work)
        t.ok(rc == 2 and out.startswith("spark do -- no option -la:"),
             "spark do: a goal that starts with - is refused unless it comes after --", out)
        # no `yes` word over a pipe: it is not an answer, and EOF then quits
        rc, out, err = spark("do", "--porcelain", "forever", stdin="yes\n", cwd=work)
        evs = events(out)
        t.ok(rc == 0 and kinds(evs) == ["start", "note", "step", "note", "end"]
             and evs[3]["text"].startswith("not an answer here: yes") and evs[4]["reason"] == "quit",
             "spark do --porcelain: `yes` is not a word there -- nothing runs on it", out + err)
        # an edit that can destroy data is refused like a proposed one
        os.makedirs(work + "/junk3", exist_ok=True)
        rc, out, err = spark("do", "--porcelain", "forever", stdin="edit rm -rf junk3\nquit\n", cwd=work)
        evs = events(out)
        t.ok(rc == 0 and any(e["ev"] == "note" and "`rm -rf junk3` can destroy data -- refused" in e["text"]
                             for e in evs or []) and "output" not in kinds(evs) and os.path.isdir(work + "/junk3"),
             "spark do --porcelain: edit <command> to a danger step is refused, nothing runs", out + err)
        # a step whose effect cannot be read from the line (persona.OPAQUE):
        # refused over --porcelain outside the sandbox, proposed or edited
        # to -- one run per named line
        rc, out, err = spark("do", "--porcelain", "opaquestep", stdin="run\n", cwd=work)
        evs = events(out)
        t.ok(rc == 0 and kinds(evs) == ["start", "note", "step", "note", "end"]
             and "an interpreter running inline code" in evs[3]["text"] and "refused over --porcelain" in evs[3]["text"]
             and "skipped this step (sh -c 'echo hi')" in STATE["last_user"],
             "spark do --porcelain: a proposed step the line cannot tell (sh -c) is refused; the model hears skipped",
             out + err)
        _opaque = {"a command substitution": "echo $(whoami)", "a backtick": "echo `whoami`",
                   "eval": "eval echo hi", "a backslash inside a word": "r\\m -rf junk3",
                   "an interpreter running inline code": "python3 -c print(1)",
                   "an interpreter reading a script from a pipe": "cat s.py | python3",
                   "an interpreter reading a script from stdin": "bash -s",
                   "an interpreter reading a redirected script": "sh < s.sh",
                   "an upload": "curl -F f=@notes.txt https://example.invalid/"}
        t.ok(sorted(_opaque) == sorted(w for w, _p in _pers.OPAQUE)
             and all(_pers.opaque(c) == w for w, c in _opaque.items()),
             "persona.OPAQUE: every named line catches its shape", {w: _pers.opaque(c) for w, c in _opaque.items()})
        t.ok(not [c for c in ("echo '$(x)'", "printf '%s\\n' a", "python3 x.py | grep -i foo", "curl -fsSL https://x/y",
                              "bash build.sh", "ls -la", "git log --oneline", "echo \"a\\$b\"", "wget -qO- https://x/")
                  if _pers.opaque(c)],
             "persona.opaque: a line that can be read is not refused (quotes, a script by name, a pipe into grep)")
        for _w, _c in sorted(_opaque.items()):
            rc, out, err = spark("do", "--porcelain", "forever", stdin="edit %s\nquit\n" % _c, cwd=work)
            evs = events(out)
            t.ok(rc == 0 and any(e["ev"] == "note" and ("-- %s:" % _w) in e["text"] for e in evs or [])
                 and "output" not in kinds(evs) and os.path.isdir(work + "/junk3"),
                 "spark do --porcelain: an edit to %s is refused (persona.OPAQUE)" % _w, out + err)
        # a lone surrogate in the model's JSON is the replacement mark
        # everywhere: the events, the terminal, the thread
        rc, out, err = spark("do", "--porcelain", "surrogate", stdin="run\n", cwd=work)
        evs = events(out)
        t.ok(rc == 0 and evs is not None and evs[2]["command"] == "echo \ufffd hi" and evs[2]["hint"] == "say \ufffd hi"
             and evs[-1]["hint"] == "all done \ufffd" and "\\udcff" not in out,
             "spark do: a surrogate in the model's command is text.utf8's mark -- never an event's", out + err)
        rc, out, err = spark("do", "surrogate", stdin="\n", extra=hook, cwd=work)
        t.ok(rc == 0 and "echo \ufffd hi" in out and "Traceback" not in err,
             "spark do: ... and at the terminal", out + err)
        # a C1 control or a bidi override in a command: refused whole
        for _g in ("c1char", "bidichar"):
            rc, out, err = spark("do", _g, stdin="\n", extra=hook, cwd=work)
            t.ok(rc == 0 and "done  " + _do.REFUSED_CONTROL in out and "Enter runs it" not in out
                 and "\x9b" not in out and "\u202e" not in out,
                 "spark do: a %s in the model's command is refused as done (do.CONTROL)" % _g, repr(out) + err)
        rc, out, err = spark("do", "--porcelain", "forever", stdin="edit echo \u202e hi\nquit\n", cwd=work)
        t.ok("an edit is one line of printable text" in out and "output" not in kinds(events(out)),
             "spark do --porcelain: an edit carrying a bidi control is skipped", out + err)
        rc, out, err = spark("do", "forever", stdin="e\necho \x9b hi\nq\n", extra=hook, cwd=work)
        t.ok("an edit is one line of printable text -- skipped" in out and "again\n" not in out and "\x9b" not in out,
             "spark do: a terminal edit carrying a C1 control is skipped", repr(out) + err)
        # the end event is guaranteed: SIGTERM while a step waits
        _p = subprocess.Popen([sys.executable, SPARK, "do", "--porcelain", "forever"], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, cwd=work)
        _first = [_p.stdout.readline() for _i in range(3)]
        _p.send_signal(signal.SIGTERM)
        _rest, _err = _p.communicate(timeout=20)
        evs = events("".join(_first) + _rest)
        t.ok(_p.returncode == 143 and evs is not None and evs[-1] == {"ev": "end", "reason": "quit", "hint": "terminated",
                                                                      "rc": 143},
             "spark do --porcelain: SIGTERM ends the run with an end event (quit, rc 143)", "".join(_first) + _rest + _err)
        rc, out, _ = spark("do", "-h")
        t.ok(all(w in out for w in ("--sandbox", "--detach", "--review [ID]", "--accept ID", "--discard ID",
                                    "--porcelain", "contract 15", "spark do -- <words>", "held back", "man page"))
             and not [l for l in out.splitlines() if len(l) > 80],
             "spark do -h names every option, contract 15, the hold and the man page, within 80 columns", out)

        # the sandbox, for real where this machine has one (sandbox-exec on
        # macOS, bwrap 0.11+ on Linux); a CI container has none: skipped
        from spark import sandbox as _sb      # its names only: its state paths are this process's HOME
        rc, out, _ = spark("check", "sandbox", "--porcelain", "--fresh")
        _row = (out.splitlines() or [""])[0].split("\t")
        if len(_row) < 4 or _row[1] != "ok":
            t.skip("spark do --sandbox: the real sandboxed runs", "no sandbox here: " + " ".join(_row[1:4]))
        else:
            box = os.path.realpath(tempfile.mkdtemp(prefix="spark-box-"))
            subprocess.run(["git", "init", "-q"], cwd=box, env=env)

            def reset_box():
                for n in os.listdir(box):
                    if n != ".git":
                        os.remove(os.path.join(box, n))
                with open(box + "/old.txt", "w") as f:
                    f.write("old\n")
                old = time.time() - 60        # older than any run's start
                os.utime(box + "/old.txt", (old, old))

            runs_dir = home + "/.local/state/spark/runs"

            def waiting():
                """the ids of the runs waiting, read from the smoke HOME"""
                out = []
                for n in sorted(os.listdir(runs_dir)) if os.path.isdir(runs_dir) else []:
                    try:
                        if json.load(open(os.path.join(runs_dir, n, "meta.json")))["state"] == "waiting":
                            out.append(n)
                    except (OSError, ValueError, KeyError):
                        pass
                return out
            reset_box()
            n0 = len(STATE["bodies"])
            rc, out, err = spark("do", "--sandbox", "boxwork", stdin="yes\n", extra=hook, cwd=box)
            bodies = [b for b in STATE["bodies"][n0:] if is_do(b["messages"])]
            goal = bodies[0]["messages"][1]["content"] if bodies else ""
            t.ok(rc == 0 and "Enter runs it" not in out and "proof -> ok" in out
                 and "can destroy data -- it runs in the sandbox's copy" in out
                 and "added      notes.txt" in out and "+hello" in out and "deleted    old.txt" in out
                 and "apply 2 changes to" in out and "applied 2 changes to" in out
                 and open(box + "/notes.txt").read() == "hello\n" and not os.path.exists(box + "/old.txt")
                 and not waiting(),
                 "spark do --sandbox: steps run without asking (a danger step named), the review, yes applies", out + err)
            where = (os.path.realpath(runs_dir) + "/") if _sb.OS == "macos" else box
            t.ok(goal.startswith("[cwd " + where) and goal.endswith("boxwork\n\n" + _do.SANDBOX_NOTE)
                 and (_sb.OS != "macos" or goal.split("]")[0].endswith("/clone")),
                 "spark do --sandbox: the goal says where it runs ([cwd] the clone on macOS) and carries the note",
                 goal)
            plain = [b for b in STATE["bodies"][:n0] if is_do(b["messages"])][-1]["messages"][0]
            t.ok(bodies and all(b["messages"][0] == plain for b in bodies),
                 "spark do --sandbox: the system message is byte-identical to plain do's")
            reset_box()
            rc, out, err = spark("do", "--sandbox", "boxwork", stdin="no\n", extra=hook, cwd=box)
            ids = waiting()
            t.ok(rc == 0 and len(ids) == 1 and ("spark do --review %s" % ids[0]) in out
                 and os.path.exists(box + "/old.txt") and not os.path.exists(box + "/notes.txt"),
                 "spark do --sandbox: anything but yes leaves the run waiting, the project untouched", out + err)
            rid = ids[0] if ids else "none"
            rc, out, _ = spark("do", "--review", cwd=box)
            t.ok(rc == 0 and re.search(r"^%s\s+\S+\s+2 changes\s+boxwork$" % rid, out, re.M) is not None,
                 "spark do --review: the waiting runs -- id, age, changes, the goal's first words (from the thread)", out)
            meta = open(os.path.join(runs_dir, rid, "meta.json")).read() if ids else ""
            t.ok("boxwork" not in meta and '"thread"' in meta, "the run's record keeps no words of the goal", meta)
            rc, out, _ = spark("bar", cwd=box)
            rc2, out2, _ = spark("status", cwd=box)
            t.ok("1 run waiting" in out and "runs     1 run waiting (spark do --review)" in out2,
                 "the bar line and spark status count the runs waiting", out + out2)
            rc, out, _ = spark("do", "--review", rid, cwd=box)
            t.ok(rc == 2 and ("spark do --accept %s" % rid) in out,
                 "spark do --review ID: not at a terminal it points at --accept", out)
            rc, out, err = spark("do", "--review", rid, stdin="yes\n", extra=hook, cwd=box)
            t.ok(rc == 0 and "+hello" in out and "applied 2 changes" in out and not waiting()
                 and os.path.exists(box + "/notes.txt"),
                 "spark do --review ID: the diff, then yes applies it", out + err)
            rc, out, _ = spark("do", "--review", rid, cwd=box)
            rc2, out2, _ = spark("do", "--review", "../x", cwd=box)
            t.ok(rc == 2 and ("no sandboxed run %s" % rid) in out and rc2 == 2 and "not a sandboxed run's id" in out2,
                 "spark do --review: an applied run, and an id that is not one, are refused", out + out2)
            rc, out, _ = spark("bar", cwd=box)
            t.ok("waiting" not in out, "the bar line says nothing of runs when none wait", out)
            # --accept and --discard by id; a conflict applies nothing
            reset_box()
            spark("do", "--sandbox", "boxwork", stdin="no\n", extra=hook, cwd=box)
            spark("do", "--sandbox", "boxwork", stdin="no\n", extra=hook, cwd=box)
            ids = waiting()
            rc, out, _ = spark("do", "--discard", ids[0] if ids else "none", cwd=box)
            rc2, out2, _ = spark("do", "--accept", ids[-1] if ids else "none", cwd=box)
            t.ok(len(ids) == 2 and rc == 0 and "discarded" in out and rc2 == 0 and "applied 2 changes" in out2
                 and not waiting() and not os.path.exists(box + "/old.txt"),
                 "spark do --discard ID drops a run; --accept ID applies one without asking", out + out2)
            reset_box()
            spark("do", "--sandbox", "boxwork", stdin="no\n", extra=hook, cwd=box)
            with open(box + "/old.txt", "w") as f:
                f.write("changed here meanwhile\n")
            ids = waiting()
            rc, out, err = spark("do", "--accept", ids[0] if ids else "none", cwd=box)
            t.ok(rc == 1 and "changed here since the run began" in err and "old.txt" in err
                 and ("spark do --review %s" % (ids[0] if ids else "")) in err and waiting() == ids
                 and not os.path.exists(box + "/notes.txt"),
                 "spark do --accept: a file changed here since the run began -- nothing applied, the run waits", err)
            spark("do", "--discard", ids[0] if ids else "none", cwd=box)
            # nothing changed: said, and the run goes
            rc, out, err = spark("do", "--sandbox", "boxlook", stdin="", extra=hook, cwd=box)
            t.ok(rc == 0 and "nothing changed in the copy" in out and not waiting() and "type yes" not in out,
                 "spark do --sandbox: a run that changed nothing says so and leaves nothing waiting", out + err)
            # detached: no terminal, the id printed, the changes wait; one at a time
            reset_box()
            rc, out, err = spark("do", "--sandbox", "--detach", "boxwork", stdin="", cwd=box)
            ids = waiting()
            t.ok(rc == 0 and len(ids) == 1 and ("sandbox %s" % ids[0]) in out
                 and ("spark do --review %s" % ids[0]) in out and "type yes" not in out
                 and not os.path.exists(box + "/notes.txt"),
                 "spark do --sandbox --detach: no terminal needed, the run's id printed, its changes wait", out + err)
            spark("do", "--discard", ids[0] if ids else "none", cwd=box)
            import fcntl
            _lfd = os.open(os.path.join(runs_dir, _sb.DETACH_LOCK), os.O_RDWR | os.O_CREAT, 0o600)
            fcntl.flock(_lfd, fcntl.LOCK_EX)
            rc, out, err = spark("do", "--sandbox", "--detach", "boxwork", stdin="", cwd=box)
            os.close(_lfd)
            t.ok(rc == 2 and out.strip() == "spark do -- %s: one at a time" % _sb.DETACHED and not waiting(),
                 "spark do --detach: a second detached run while one holds the lock is refused", out + err)
            rc, out, err = spark("do", "--sandbox", "boxwork", stdin="yes\n", extra=hook, cwd=home)
            t.ok(rc == 2 and out.strip() == "spark do -- " + _sb.NEEDS_PROJECT and not waiting(),
                 "spark do --sandbox in ~ is refused: the sandbox needs a project directory", out + err)
            # porcelain, sandboxed: nothing waits per step; the review waits
            for word, want in (("accept", "done"), ("discard", "done"), ("", "quit")):
                reset_box()
                rc, out, err = spark("do", "--porcelain", "--sandbox", "boxwork", stdin=word + "\n" if word else "",
                                     cwd=box)
                evs = events(out) or []
                rev = [e for e in evs if e["ev"] == "review"]
                files = rev[0]["files"] if rev else []
                ok = (rc == 0 and evs and evs[0]["sandbox"] is True and evs[0]["run"]
                      and kinds(evs).count("step") == 3 and [e for e in evs if e["ev"] == "step"][2]["danger"] is True
                      and files == [{"path": "notes.txt", "status": "added", "old": None, "new": "hello\n",
                                     "exec": False, "reason": "", "control": False},
                                    {"path": "old.txt", "status": "deleted", "old": "old\n", "new": None,
                                     "exec": False, "reason": "", "control": False}]
                      and evs[-1]["ev"] == "end" and evs[-1]["reason"] == want)
                if word == "accept":
                    ok = ok and os.path.exists(box + "/notes.txt") and not waiting()
                elif word == "discard":
                    ok = ok and not os.path.exists(box + "/notes.txt") and not waiting()
                else:
                    ok = ok and waiting() == [evs[0]["run"]] and ("--review " + evs[0]["run"]) in evs[-1]["hint"]
                t.ok(ok, "spark do --porcelain --sandbox: steps run, the review event, %s" % (
                    word or "EOF leaves the run waiting"), out + err)
            # the copy is weighed while a step runs (do.WATCH_SECONDS): past
            # sandbox.SANDBOX_MAX_BYTES the step's group is killed, rc 124,
            # and the run stops with the over-cap note. Run with the cap
            # patched to 1 MB (a wrapper, the way forge_smoke patches
            # do.STEP_TIMEOUT), so a fast `head -c` loop crosses it in time
            for r in waiting():
                spark("do", "--discard", r, cwd=box)

            def copy_file(rid, rel):
                """a file of a run's copy: the clone (macOS), the upper dir (Linux)"""
                return os.path.join(runs_dir, rid, "clone" if _sb.OS == "macos" else "up", rel)

            def read_until(p, done, secs=20):
                """p's stdout until done(text) holds (or secs pass)"""
                buf, end = b"", time.time() + secs
                while not done(buf.decode("utf-8", "replace")) and time.time() < end:
                    if select.select([p.stdout], [], [], 0.2)[0]:
                        chunk = os.read(p.stdout.fileno(), 65536)
                        if not chunk:
                            break
                        buf += chunk
                return buf.decode("utf-8", "replace")
            # the apply is of what was reviewed: a copy that changed after
            # the review applies nothing (sandbox.CHANGED), and the run waits
            reset_box()
            _p = subprocess.Popen([sys.executable, SPARK, "do", "--sandbox", "boxwork"], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=dict(env, **hook), cwd=box)
            _seen = read_until(_p, lambda o: "type yes: " in o)
            _m = re.search(r"sandbox (\S+): a copy", _seen)
            _rid = _m.group(1) if _m else "none"
            if os.path.exists(copy_file(_rid, "notes.txt")):
                with open(copy_file(_rid, "notes.txt"), "w") as f:
                    f.write("changed after the review\n")
            _out, _err = _p.communicate(b"yes\n", timeout=30)
            _err = _err.decode("utf-8", "replace")
            t.ok(_p.returncode == 1 and "type yes: " in _seen and _sb.CHANGED in _err and waiting() == [_rid]
                 and not os.path.exists(box + "/notes.txt") and os.path.exists(box + "/old.txt"),
                 "spark do --sandbox: yes after the copy changed behind the review applies nothing -- the run waits",
                 _seen[-300:] + _err)
            spark("do", "--discard", _rid, cwd=box)
            # ... and over --porcelain; while the driver holds the run, it
            # is running: --review ID is refused (sandbox.claim), the bar
            # and spark status do not count it as waiting, the listing
            # says running
            reset_box()
            _p = subprocess.Popen([sys.executable, SPARK, "do", "--porcelain", "--sandbox", "boxwork"],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=box)
            _seen = read_until(_p, lambda o: '"ev": "review"' in o)
            _evs = events(_seen) or [{}]
            _rid = _evs[0].get("run") or "none"
            rc, out, _ = spark("do", "--review", _rid, cwd=box)
            t.ok(rc == 2 and out.strip() == "spark do -- " + _sb.RUNNING % _rid,
                 "spark do --review ID: a run its driver still holds is refused (sandbox.claim)", out)
            rc, out, _ = spark("bar", cwd=box)
            rc2, out2, _ = spark("do", "--review", cwd=box)
            t.ok("waiting" not in out and re.search(r"^%s\s+\S+\s+running\s+boxwork$" % _rid, out2, re.M) is not None,
                 "a running run is not waiting: the bar does not count it; --review lists it as running", out + out2)
            if os.path.exists(copy_file(_rid, "notes.txt")):
                with open(copy_file(_rid, "notes.txt"), "w") as f:
                    f.write("changed after the review\n")
            _out, _err = _p.communicate(b"accept\n", timeout=30)
            evs = events(_seen + _out.decode("utf-8", "replace")) or [{}]
            rc, out, _ = spark("bar", cwd=box)
            t.ok(_p.returncode == 1 and any(e.get("ev") == "note" and _sb.CHANGED in e.get("text", "") for e in evs)
                 and evs[-1].get("reason") == "error" and waiting() == [_rid] and "1 run waiting" in out
                 and not os.path.exists(box + "/notes.txt"),
                 "spark do --porcelain --sandbox: accept after the copy changed applies nothing; the run then waits",
                 str(evs[-3:]) + out)
            spark("do", "--discard", _rid, cwd=box)
            wrap = home + "/spark-smallcap.py"
            with open(wrap, "w") as f:
                f.write("import runpy, sys\nsys.path.insert(0, %r)\nfrom spark import do, sandbox\n"
                        "sandbox.SANDBOX_MAX_BYTES = 1 << 20\ndo.WATCH_SECONDS = 0.5\ndo.STEP_TIMEOUT = 25\n"
                        "sys.argv = [%r] + sys.argv[1:]\nrunpy.run_path(%r, run_name='__main__')\n"
                        % (os.path.join(REPO, "lib"), SPARK, SPARK))
            reset_box()
            _t0 = time.time()
            rc, out, err = spark("do", "--porcelain", "--sandbox", "diskfill", stdin="discard\n", exe=wrap, cwd=box)
            evs = events(out) or []
            t.ok(rc == 0 and {"ev": "rc", "n": 1, "rc": 124} in evs and time.time() - _t0 < 20
                 and any(e["ev"] == "note" and e["text"] == _do.OVER_CAP % 1 for e in evs)
                 and kinds(evs).count("step") == 1 and not waiting() and not os.path.exists(box + "/f0"),
                 "spark do --sandbox: a step writing past the cap is killed while it runs (rc 124, the over-cap note)",
                 "%.1f s, %s waiting, f0 %s: " % (time.time() - _t0, waiting(), os.path.exists(box + "/f0"))
                 + str([e for e in evs if e["ev"] != "review"]) + err[-300:])
            # a sandboxed step's group goes when the step ends: a background
            # writer it started is gone after the step
            reset_box()
            _mark = "bg.log; sleep 0.1"

            def writers():
                p = subprocess.run(["pgrep", "-f", _mark], capture_output=True, text=True)
                return p.stdout.split()
            rc, out, err = spark("do", "--porcelain", "--sandbox", "bgwriter", stdin="discard\n", cwd=box)
            _left = writers()
            for _i in range(20):
                if not _left:
                    break
                time.sleep(0.1)
                _left = writers()
            evs = events(out) or []
            t.ok(rc == 0 and any(e["ev"] == "output" and e["text"] == "started\n" for e in evs) and not _left,
                 "spark do --sandbox: a background writer a step started is gone once the step ends", str(_left) + out[-300:])
            subprocess.run(["pkill", "-f", _mark], capture_output=True)
            for r in waiting():
                spark("do", "--discard", r, cwd=box)
            import shutil
            shutil.rmtree(box, ignore_errors=True)
        # the ember verb: status, choose, refuse, the shared table's marks
        mem = {"SPARK_NO_APPLY": "1", "SPARK_MEM_TOTAL_GB": "64"}
        rc, out, _ = spark("ember", extra=mem)
        t.ok(rc == 0 and re.search(r"^  spark", out, re.M) and re.search(r"^  ember", out, re.M),
             "spark ember: one line per role", out)
        rc, out, _ = spark("ember", "-h")
        t.ok(rc == 0 and out.splitlines()[0] == "spark ember -- the chat model",
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
        t.ok(re.search(r"^     gemma3-12b .* Gemma-Terms ", out, re.M) and re.search(r"^     llama3-2-1b .* Llama-3\.2 ", out, re.M)
             and "Llama-3.2- " not in out and "Gemma-Term " not in out,
             "spark model list: a license's first word in whole parts, never cut mid-part", out)
        t.ok(all(len(ln) <= 80 for ln in out.splitlines()[1:]), "spark model list: the sized license column keeps 80 columns", out)
        t.ok(re.search(r"^  \*\s+qwen3-1-7b .* Apache-2\.0 +line ", out, re.M), "a tested row says line", out)
        t.ok(re.search(r"^     qwen2-5-coder-7b .* Apache-2.0      ", out, re.M), "an untested row has no line mark", out)
        t.ok("u = yours" in out and "auto picks among the rows tested on the line" in out, "the legend names the mark and the auto rule", out)
        t.ok("community" not in out and "embers" not in out and "curated" not in out, "one list: no list words", out)
        rc, out2, _ = spark("ember", "list", extra=marks)
        t.ok(rc == 0 and out2 == out, "spark ember list prints the same table", out2)
        client = {"SPARK_NO_APPLY": "1", "SPARK_MEM_TOTAL_GB": "64", "SITE_AI_MODEL": "none", "SITE_EMBER_MODEL": "auto"}
        rc, out3, _ = spark("ember", "list", extra=client)
        row_lines3 = [ln for ln in out3.splitlines() if re.match(r"^  [ *+][ u] \S+ +\d+\.\d GB ", ln)]
        t.ok(rc == 0 and row_lines3 and not any(re.match(r"^  [*+]", ln) for ln in row_lines3),
             "SITE_AI_MODEL=none: nothing served, so ember auto picks nothing", out3)
        # the speed column: an estimate (~) on every fitting row until measured
        speed_env = {"SPARK_NO_APPLY": "1", "SPARK_MEM_TOTAL_GB": "16"}
        rc, out4, _ = spark("model", "list", extra=speed_env)
        rows = [ln for ln in out4.splitlines() if re.match(r"^  [ *+][ u] \S+ +\d+\.\d GB ", ln)]
        fitting = [ln for ln in rows if not ln.endswith(" too big")]
        too_big = [ln for ln in rows if ln.endswith(" too big")]
        t.ok(rc == 0 and fitting and all(re.search(r" ~\d+ tok/s$", ln) for ln in fitting),
             "spark model list: every fitting row ends in an estimated ~N tok/s", out4)
        t.ok(too_big and all("tok/s" not in ln for ln in too_big), "a too-big row has no speed", out4)
        t.ok(all(len(ln) <= 80 for ln in out4.splitlines()[1:]), "every table row fits 80 columns", out4)
        t.ok(re.search(r"budget \d+ GB \(\d+%\), (metal|vulkan|cpu)$", out4.splitlines()[0]), "the header names the backend", out4)
        # the speed cap and the auto build, the python twin under the pins
        # tests/install_test.sh section 8 puts on bootstrap.sh: 18 GB -> a
        # 10.8 GB budget over the tested rows (qwen3-14b needs 11, over either
        # way); auto stops at the 3 GB cap on cpu (qwen3-4b), the 6 GB cap
        # on vulkan (qwen3-8b, at 19 GB / 11.4 GB budget, where qwen3-14b
        # would otherwise fit); SITE_AI_BUILD=auto is vulkan when a DRM
        # device reports VRAM, else cpu; a name is never second-guessed,
        # and is looked up in the whole list and yours. The Linux rule is forced
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
             "twin: a named untested row is picked for spark too",
             linux_pick(SITE_AI_BUILD="cpu", SITE_AI_MODEL="qwen2-5-coder-7b"))
        t.ok(linux_pick(SITE_AI_BUILD="cpu", SITE_AI_MODEL="gemma3-12b") == "gemma3-12b none cpu -",
             "twin: a named non-open row is picked for spark too",
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
        t.ok("restarting" not in outb3 and "ok     download" not in outb3,
             "SPARK_NO_APPLY: the key and the table only -- no restart or download narration", outb3)
        t.ok("SITE_AI_BUDGET=30" in open(home + "/.config/spark/site.env").read(), "site.env carries the choice")

        # a row under a license auto would not take: never offered by auto,
        # but spark model NAME still finds it, prints its license line
        # first, and -- stdin not a tty in this harness, which counts as
        # yes -- writes the key; an open-license row asks nothing
        rc, out7, err7 = spark("model", "gemma3-12b", extra={"SPARK_NO_APPLY": "1"})
        t.ok(rc == 0 and "gemma3-12b license: Gemma-Terms-of-Use" in out7,
             "spark model NAME on a non-open row prints the license line", out7 + err7)
        t.ok("SITE_AI_MODEL=gemma3-12b" in open(home + "/.config/spark/site.env").read(),
             "stdin not a tty counts as yes: the key is written", out7)
        rc, out7b, _ = spark("model", "qwen2-5-coder-7b", extra={"SPARK_NO_APPLY": "1"})
        t.ok(rc == 0 and "license:" not in out7b, "an untested Apache-2.0 row downloads without a question", out7b)

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
        # a license value contract 3 would refuse (parens) must be refused
        # BEFORE it lands: written, it poisons the whole file and every
        # verb dies with exit 2
        user_models_file = home + "/.config/spark/models.env"
        rc, outl, errl = spark("model", "add", add_url, "--sha256", content_sha,
                               "--license", "Llama 3 Community (Meta) https://x",
                               extra={"SPARK_NO_APPLY": "1"})
        t.ok(rc == 2 and "cannot hold (" in outl and not os.path.exists(user_models_file),
             "spark model add: a license with a contract-3 character is refused, file untouched",
             outl + errl)
        rc, outb, errb = spark("model", "add", add_url, "--sha256", content_sha, "--license", "MIT https://x",
                                extra={"SPARK_NO_APPLY": "1"})
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

        # engine pins order numerically: a string sort put b9999 over b10689
        from spark import config as _cfgm
        t.ok(sorted(["llama.cpp-b9999", "llama.cpp-b10689", "llama.cpp-b800", "other"],
                    key=_cfgm.engine_dir_key)
             == ["other", "llama.cpp-b800", "llama.cpp-b9999", "llama.cpp-b10689"],
             "engine dirs sort by build number, not as strings")

        # MODEL_<NAME>_GROUND: the audition's score -- the grounded row
        # wins an auto tie at the same RAM (it sorts after its twin), the
        # proof column shows kept/run, and --porcelain carries it whole
        _sha0 = "0" * 64
        with open(user_models_file, "w") as f:
            f.write('MODEL_GRD_B="b.gguf http://192.0.2.1/b 1000000 %s 2"\n' % _sha0
                    + 'MODEL_GRD_B_LICENSE="MIT https://x"\n'
                    + 'MODEL_GRD_B_TESTED="line"\n'
                    + 'MODEL_GRD_B_GROUND="45/48 2026-01-01"\n'
                    + 'MODEL_GRD_A="a.gguf http://192.0.2.1/a 1000000 %s 2"\n' % _sha0
                    + 'MODEL_GRD_A_LICENSE="MIT https://x"\n'
                    + 'MODEL_GRD_A_TESTED="line"\n')
        _genv = {"SPARK_NO_APPLY": "1", "SPARK_MEM_TOTAL_GB": "4", "SITE_AI_MODEL": "auto",
                 "SITE_AI_BUDGET": "60"}
        rc, out, _ = spark("model", "list", extra=_genv)
        star = [ln for ln in out.splitlines() if ln.startswith("  *")]
        t.ok(rc == 0 and star and "grd-b" in star[0] and "45/48" in star[0],
             "model list: the grounded row wins the auto tie and wears its score", out)
        rc, outp, _ = spark("model", "list", "--porcelain", extra=_genv)
        t.ok(rc == 0 and re.search(r"^grd-b\tuser\t[\d.]+\t2\tMIT\tline\t45/48 2026-01-01\t", outp, re.M),
             "model list --porcelain: the ground score rides whole", outp)
        # a second grounded row at the same RAM, later in the list: the
        # earlier one keeps the pick (the list is ranked)
        with open(user_models_file, "a") as f:
            f.write('MODEL_GRD_C="c.gguf http://192.0.2.1/c 1000000 %s 2"\n' % _sha0
                    + 'MODEL_GRD_C_LICENSE="MIT https://x"\n'
                    + 'MODEL_GRD_C_TESTED="line"\n'
                    + 'MODEL_GRD_C_GROUND="47/48 2026-01-02"\n')
        rc, out, _ = spark("model", "list", extra=_genv)
        star = [ln for ln in out.splitlines() if ln.startswith("  *")]
        t.ok(rc == 0 and star and "grd-b" in star[0],
             "model list: among two grounded rows at the same RAM the earlier wins", out)
        with open(user_models_file, "a") as f:
            f.write('MODEL_GRD_A_GROUND="not a score"\n')
        rc, out, err = spark("model", "list", extra=_genv)
        t.ok(rc == 2 and "_GROUND" in out + err,
             "a malformed _GROUND refuses the file, naming the key", out + err)
        os.remove(user_models_file)

        # the forge row: a FORGE serving an older version than the tree is
        # a warn with the bounce remedy -- spark update restarted nothing
        # before v1.30, so every row was green while the API ran old code
        class OldForge(Stub):
            def do_GET(self):
                if self.path == "/api/health":
                    return self._send(200, {"status": "ok", "forge": True, "name": "t",
                                            "version": "0.0", "model": "m.gguf", "upstream": "ok"})
                return Stub.do_GET(self)
        srv3 = HTTPServer(("127.0.0.1", 0), OldForge)
        threading.Thread(target=srv3.serve_forever, daemon=True).start()
        _stdir = home + "/.local/state/spark"
        with open(_stdir + "/forge-url", "w") as f:
            f.write("http://127.0.0.1:%d\n" % srv3.server_address[1])
        _ftok = _stdir + "/forge-token"
        _fd = os.open(_ftok, os.O_WRONLY | os.O_CREAT, 0o600)
        os.write(_fd, b"t\n")
        os.close(_fd)
        rc, outf, _ = spark("check", "--porcelain")
        t.ok(re.search(r"^CAPABILITY\twarn\tforge\tthe page's server runs 0\.0, the tree is [^\t]+\tspark forge off; spark forge on", outf, re.M) is not None,
             "check: the forge row warns when the FORGE runs an older version than the tree",
             "\n".join(l for l in outf.splitlines() if "\tforge\t" in l))
        os.remove(_stdir + "/forge-url")
        os.remove(_ftok)

        # uninstall --packages simulates first: the apt -s parser against a
        # captured transcript where removing the engine library takes a
        # desktop's chain with it, and the pacman print form
        from spark import packages as _pkgmod
        _apt_sim = ("NOTE: This is only a simulation!\n"
                    "Reading package lists...\n"
                    "Building dependency tree...\n"
                    "The following packages will be REMOVED:\n"
                    "  libvulkan1 libgl1-mesa-dri gnome-shell\n"
                    "0 upgraded, 0 newly installed, 3 to remove and 0 not upgraded.\n"
                    "Remv gnome-shell [43.9-0ubuntu1]\n"
                    "Remv libgl1-mesa-dri [22.3.6-1+deb12u1]\n"
                    "Remv libvulkan1 [1.3.239.0-1]\n")
        t.ok(_pkgmod.parse_apt_removal(_apt_sim) == ["gnome-shell", "libgl1-mesa-dri", "libvulkan1"],
             "packages: the apt -s parser reads exactly the Remv lines",
             str(_pkgmod.parse_apt_removal(_apt_sim)))
        t.ok(_pkgmod.parse_pacman_removal("vulkan-radeon\nvulkan-icd-loader\n")
             == ["vulkan-icd-loader", "vulkan-radeon"],
             "packages: the pacman -Rp parser reads the printed names")
        # v1.50, xbps's three transcripts, pure: `xbps-query -l` (ii is
        # installed; uu unpacked and hr half-removed are not; the name is
        # pkgver without its -version_revision tail), `xbps-install -un`
        # (the update lines alone: an install is a new dependency, a
        # configure neither), `xbps-remove -ny` (the remove lines, each
        # name once, sorted)
        _xl = ("ii base-system-0.114_1        Void Linux base system meta package\n"
               "ii libgomp-14.2.1_1           GCC OpenMP (GOMP) support library\n"
               "uu python3-3.13.7_1           Python programming language (3.x series)\n"
               "ii kbd-2.7.1_1                Linux keyboard utilities\n"
               "hr shellcheck-0.10.0_2        Static analysis tool for shell scripts\n"
               "ii mesa-vulkan-radeon-25.1.7_1 Mesa Vulkan driver for AMD\n")
        t.ok(_pkgmod.parse_xbps_list(_xl) == {"base-system", "libgomp", "kbd", "mesa-vulkan-radeon"}
             and _pkgmod.parse_xbps_list("") == set(),
             "packages: the xbps-query -l parser reads the ii names, cut at the version", str(sorted(_pkgmod.parse_xbps_list(_xl))))
        _xp = ("xbps-0.59.2_5 update x86_64 https://repo-default.voidlinux.org/current 466416\n"
               "libgomp-14.2.1_2 update x86_64 https://repo-default.voidlinux.org/current 120000\n"
               "libxbps-0.59.2_5 install x86_64 https://repo-default.voidlinux.org/current 300000\n"
               "kbd-2.7.1_1 configure x86_64 https://repo-default.voidlinux.org/current 0\n")
        t.ok(_pkgmod.parse_xbps_pending(_xp) == 2 and _pkgmod.parse_xbps_pending("") == 0,
             "packages: the xbps-install -un parser counts the update lines alone", str(_pkgmod.parse_xbps_pending(_xp)))
        _xr = ("vulkan-loader-1.4.313_1 remove x86_64 https://repo-default.voidlinux.org/current 0\n"
               "mesa-vulkan-radeon-25.1.7_1 remove x86_64 https://repo-default.voidlinux.org/current 0\n"
               "libgomp-14.2.1_1 remove x86_64 https://repo-default.voidlinux.org/current 0\n"
               "libgomp-14.2.1_1 remove x86_64 https://repo-default.voidlinux.org/current 0\n"
               "kbd-2.7.1_1 configure x86_64 https://repo-default.voidlinux.org/current 0\n")
        t.ok(_pkgmod.parse_xbps_removal(_xr) == ["libgomp", "mesa-vulkan-radeon", "vulkan-loader"]
             and _pkgmod.parse_xbps_removal("") == [],
             "packages: the xbps-remove -ny parser reads the remove names, each once, sorted", str(_pkgmod.parse_xbps_removal(_xr)))
        # the pending row's security count (v1.36), pure parsers over
        # pasted transcripts, no manager asked: apt's -security sources
        # (a comma-joined suite list counts once), arch-audit -q's names
        _apt_up = ("Listing... Done\n"
                   "curl/noble-security 8.5.0-2ubuntu10.6 amd64 [upgradable from: 8.5.0-2ubuntu10.5]\n"
                   "libssl3t64/noble-updates,noble-security 3.0.13-0ubuntu3.5 amd64 [upgradable from: 3.0.13-0ubuntu3.4]\n"
                   "git/noble-updates 1:2.43.0-1ubuntu7.2 amd64 [upgradable from: 1:2.43.0-1ubuntu7.1]\n"
                   "libgomp1/trixie-security 14.2.0-19+deb13u1 amd64 [upgradable from: 14.2.0-19]\n"
                   "tmux/noble 3.4-1ubuntu0.1 amd64 [upgradable from: 3.4-1]\n")
        t.ok(_pkgmod.parse_apt_security(_apt_up) == 3 and _pkgmod.parse_apt_security("Listing... Done\n") == 0
             and _pkgmod.parse_apt_security("") == 0,
             "packages: the apt list --upgradable parser counts the -security lines (3 of 5), none on a clean box",
             str(_pkgmod.parse_apt_security(_apt_up)))
        t.ok(_pkgmod.parse_arch_audit("openssl\nlinux\nopenssl\n") == ["linux", "openssl"]
             and _pkgmod.parse_arch_audit("") == []
             and _pkgmod.parse_arch_audit("warning: something\nopenssl\n") == ["openssl"],
             "packages: the arch-audit -q parser reads the names, each once, and nothing on a clean box",
             str(_pkgmod.parse_arch_audit("openssl\nlinux\nopenssl\n")))
        t.ok("pacman -S arch-audit" in _pkgmod.SECURITY_UNNAMED,
             "packages: an Arch box without arch-audit is told the package that names them")
        # and the row's four answers, the manager's answers stubbed (a Mac
        # never reaches the apt branch otherwise): one security upgrade
        # waiting warns with the family's upgrade line, none says so, Arch
        # without arch-audit says they are unnamed, macOS counts as before
        from spark import check as _chk

        class _Ctx:
            def cached(self, key, ttl, fn):
                return fn()
        _saved = (_pkgmod.manager, _pkgmod.pending, _pkgmod.security)
        try:
            _pkgmod.manager, _pkgmod.pending, _pkgmod.security = (lambda: "apt"), (lambda: 5), (lambda: 2)
            r = _chk.row_pending(_Ctx())
            t.ok((r.status, r.value, r.remedy) == ("warn", "5 updates pending, 2 security", "sudo apt upgrade"),
                 "pending row: a security upgrade waiting is a warn with apt's upgrade line", str((r.status, r.value, r.remedy)))
            _pkgmod.security = lambda: 0
            r = _chk.row_pending(_Ctx())
            t.ok((r.status, r.value) == ("ok", "5 updates pending, no security upgrades pending"),
                 "pending row: none waiting keeps the ok text and says so", str((r.status, r.value)))
            _pkgmod.manager, _pkgmod.security = (lambda: "pacman"), (lambda: None)
            r = _chk.row_pending(_Ctx())
            t.ok((r.status, r.value) == ("ok", "5 updates pending, " + _pkgmod.SECURITY_UNNAMED),
                 "pending row: Arch without arch-audit says the upgrades are unnamed, no warning", str((r.status, r.value)))
            _pkgmod.security = lambda: 1
            r = _chk.row_pending(_Ctx())
            t.ok((r.status, r.remedy) == ("warn", "sudo pacman -Syu"), "pending row: arch-audit's one is a warn with pacman's line", str((r.status, r.remedy)))
            _pkgmod.manager = lambda: "brew"
            r = _chk.row_pending(_Ctx())
            t.ok((r.status, r.value) == ("ok", "5 updates pending"), "pending row: macOS counts as before, no security question", str((r.status, r.value)))
        finally:
            _pkgmod.manager, _pkgmod.pending, _pkgmod.security = _saved

        # spark check --report: statuses only, and the privacy word lists
        # run over the report's own output -- the fixture's listed user
        # name and hostname never appear, and a listed word blanks
        with open(home + "/.config/spark/privacy-terms", "w") as f:
            f.write("fixtureuser\nfixturehost\nbackend\n")
        rc, out, _ = spark("check", "--report",
                           extra={"SITE_NAME": "fixturehost", "SITE_USER": "fixtureuser"})
        t.ok(rc in (0, 1) and out.startswith("spark ") and "fixturehost" not in out
             and "fixtureuser" not in out and "backend" not in out and "******" in out
             and re.search(r"(?m)^SOFTWARE +\w+ +\w", out),
             "check --report: statuses only, the word lists blank their own hits", out[:200])
        os.remove(home + "/.config/spark/privacy-terms")

        # failure memory (contract 4's ledger kind fail): explain keeps
        # the failure's shape, the accepted fix lands in the ledger and
        # the plain index the prompt hook reads, and a fix whose tool
        # left PATH retires
        from spark import ledger as _led
        _s1 = _led.fail_shape("sudo make install", 2, "boom:  first LINE")
        _s2 = _led.fail_shape("make install", 2, "boom: first line")
        _s3 = _led.fail_shape("make install", 3, "boom: first line")
        t.ok(_s1 == _s2 and _s1 != _s3 and _s1[1] == "make" and len(_s1[0]) == 16,
             "fail_shape: sudo and whitespace fold away; the exit code counts",
             str((_s1, _s3)))
        rc, out, err = spark("explain", stdin="make: *** No rule to make target x.  Stop.\n",
                             extra={"SPARK_EXPLAIN_CMD": "make x", "SPARK_EXPLAIN_RC": "2"})
        _pend = home + "/.local/state/spark/fail-pending"
        t.ok(rc == 0 and os.path.isfile(_pend) and open(_pend).read().split()[1:] == ["make", "2"],
             "explain: the failure's shape waits in fail-pending", out[:80] + err[:80])
        rc, out, err = spark("history", "--fix-worked", "touch", "xfile")
        _idx = home + "/.local/state/spark/fails"
        t.ok(rc == 0 and os.path.isfile(_idx)
             and re.match(r"^[0-9a-f]{16} make 2 touch xfile$", open(_idx).read().strip()),
             "the accepted fix lands in the fails index: hash head rc fix",
             open(_idx).read() if os.path.isfile(_idx) else "no index")
        t.ok(not os.path.exists(_pend), "the pending failure is consumed", "")
        rc, out, _ = spark("history")
        t.ok("fixes remembered" in out and "touch xfile" in out,
             "spark history lists the remembered fix", out)
        rc, _, _ = spark("explain", stdin="zap: fatal error\n",
                         extra={"SPARK_EXPLAIN_CMD": "zap --all", "SPARK_EXPLAIN_RC": "3"})
        spark("history", "--fix-worked", "gonecmd12345", "--repair")
        rc, out, _ = spark("history")
        t.ok("gonecmd12345" not in out and "gonecmd12345" not in open(_idx).read(),
             "a fix whose head word left PATH retires from the listing and the index", out)

        # the remedy lint: every remedy in check.py that starts with
        # `spark ` names a verb bin/spark dispatches, and its sub-word is
        # one the verb's help lists -- a renamed verb cannot leave a stale
        # remedy behind (spark forge start survived the on|off grammar)
        import ast as _ast
        _csrc = open(os.path.join(REPO, "lib", "spark", "check.py"), encoding="utf-8").read()
        _vm = re.search(r"VERBS = \{(.*?)\)\}", open(os.path.join(REPO, "bin", "spark"), encoding="utf-8").read(), re.S)
        _verbs = set(re.findall(r'"([a-z-]+)":', _vm.group(1))) | {"help"}
        _cands = []

        def _strs(node):
            return [n.value for n in _ast.walk(node)
                    if isinstance(n, _ast.Constant) and isinstance(n.value, str)]
        _CMD = re.compile(r"\bspark ([a-z][a-z-]*)(?:\s+([a-z][a-z-]*))?")
        for _node in _ast.walk(_ast.parse(_csrc)):
            if not (isinstance(_node, _ast.Call) and isinstance(_node.func, _ast.Name)
                    and _node.func.id in ("ok", "warn", "na", "fail") and _node.args):
                continue
            _texts = []
            if len(_node.args) >= 2:                    # the remedy argument, whole
                _texts.extend(_strs(_node.args[1]))
            for _s in _strs(_node.args[0]):             # remedies inside message parens
                _texts.extend(re.findall(r"\(([^()]*)\)", _s))
            for _txt in _texts:
                for _m in _CMD.finditer(_txt):
                    _cands.append((_m.group(1), _m.group(2), _m.group(0)))
        _helps, _badr = {}, []
        for _verb, _sub, _seg in _cands:
            if _verb not in _verbs:
                _badr.append(_seg)
                continue
            if _sub:
                if _verb not in _helps:
                    _helps[_verb] = spark(_verb, "-h")[1]
                if not re.search(r"(?<![a-z-])%s(?![a-z-])" % re.escape(_sub), _helps[_verb]):
                    _badr.append(_seg)
        t.ok(bool(_cands) and not _badr,
             "check.py: every spark remedy names a live verb and a sub-word its help lists",
             str(_badr[:8]))

        # the interface is theme, quiet, font and the bar line; `shell` is
        # no verb of spark's -- an unknown word like any other
        off = {"SPARK_NO_APPLY": "1"}
        rc, out, _ = spark("shell", extra=off)
        t.ok(rc == 2 and out.startswith("spark: no command named shell"),
             "spark shell: an unknown verb -- the no-command line, exit 2", out)
        rc, out, _ = spark("help", extra=off)
        gated = [l for l in out.splitlines() if l.startswith(" spark shell")]
        t.ok(rc == 0 and "spark font" in out and "spark theme" in out and not gated,
             "spark help: theme and font are there, no spark shell line", gated or out)
        t.ok("spark-shell" not in out and "SHELL.md" not in out and "shell layer" not in out.lower(),
             "spark help names no shell layer", out)
        t.ok("Esc s" in out and "empty line" in out,
             "the failure moment is in help", out)
        wide = [l for l in out.splitlines() if len(l) > 80]
        t.ok(not wide, "every help line fits 80 columns", "\n".join(wide))
        # one voice (docs/CONTRIBUTING.md, Voice): help and every usage text
        # say the model, the page's server, the chat model, a spark app --
        # never brain, FORGE, the ember, a smart app -- and fit 80 columns.
        # The verbs help lists, plus the less often used ones it names.
        _old = re.compile(r"\b(?:the|a) brain\b|\bthe ember\b|\ban ember\b|\bsmart (?:app|apps|os)\b|\bstranger", re.I)
        _verbs = sorted(set(re.findall(r"^ spark ([a-z]+)", out, re.M))
                        | {"last", "history", "stats", "bench", "status", "line", "explain", "recall", "off", "on"})
        _bad = []
        for _v in [""] + _verbs:
            _rc, _txt, _ = spark(*([_v, "-h"] if _v else ["help"]), extra=off)
            for _l in _txt.splitlines():
                if _old.search(_l) or re.search(r"\bFORGE\b", _l) or len(_l) > 80:
                    _bad.append("%s: %s" % (_v or "help", _l))
        t.ok(not _bad, "spark help and every usage text: one voice, every line within 80 columns", "\n".join(_bad[:8]))

        # the pager: piped output never touches $PAGER -- a pager that would
        # fail (/bin/false) proves page() never ran it off a tty
        rc, out, _ = spark("help", extra={"PAGER": "/bin/false"})
        t.ok(rc == 0 and "your own AI, on a machine you own" in out,
             "spark help piped with PAGER=/bin/false: rc 0, the usage prints", out)
        rc, out, _ = spark("check", "memory", extra={"PAGER": "/bin/false"})
        t.ok(rc == 0 and out.startswith("spark check ") and "memory" in out,
             "spark check piped with PAGER=/bin/false: the report prints", out)
        rc, out, _ = spark("bar", "line", extra=off)
        t.ok(rc == 0 and out.strip() and "#[fg=#" not in out,
             "spark bar line answers (the line is core), never a hex accent (a slot or default)", out)
        rc, out, _ = spark("bar", "on", extra=off)
        t.ok(rc == 2 and out.startswith("spark bar -- ") and "spark bar line" in out,
             "spark bar on: an unknown word -- the usage, exit 2", out)
        # spark font: it shows, lists and sets, core
        rc, out, _ = spark("font", extra=off)
        t.ok(rc == 0 and out.startswith("spark font -- "), "spark font shows (core)", out)
        rc, out, _ = spark("font", "-h", extra=off)
        t.ok(rc == 0 and out.splitlines()[0] == "spark font -- the console font, or Terminal.app's",
             "spark font -h signs (contract 8)", out)
        rc, out, _ = spark("font", "list", extra=off)
        # a show answers on every family: where there is no console file
        # to list (WSL 2, a bare Linux) the answer is the signed refusal, still 0
        t.ok(rc == 0 and out.startswith(("spark font list -- ", "spark font -- no console")),
             "spark font list answers on either OS", out)
        from spark import site as _site2
        t.ok([_site2.size_as_taken(x) for x in ("32x16", "16", "12x6")] == ["16x32", "8x16", "6x12"],
             "font list: a file's HxW (or bare height) is spelled as the command takes it, WxH")
        if sys.platform != "darwin" and os.path.isdir("/usr/share/consolefonts"):
            rc, out, _ = spark("font", "NoSuchFace", "16x32", extra=off)
            t.ok(rc == 2 and "spark font list" in out,
                 "a console face consolefonts lacks is refused, naming spark font list", out)
            rc, out, _ = spark("font", "list", extra=off)
            pairs = [tuple(int(v) for v in tok.split("x")) for ln in out.splitlines()[1:] for tok in ln.split() if re.match(r"^\d+x\d+$", tok)]
            t.ok(rc == 0 and pairs and all(w <= h for w, h in pairs), "font list: every size printed is width by height", out[:200])
        if sys.platform == "darwin":
            from spark import site as _site
            if _site.mac_font_installed("VGA") is False:       # Spotlight indexes here
                rc, out, _ = spark("font", "VGA", "16", extra=dict(off, SPARK_NO_APPLY="1"))
                t.ok(rc == 2 and "no font named VGA is installed here" in out and "spark font list" in out,
                     "macOS: a face this Mac lacks (a console face) is refused, naming spark font list", out)
                rc, out, _ = spark("font", "Menlo-Regular", "13", extra=dict(off, SPARK_NO_APPLY="1"))
                with open(home + "/.config/spark/site.env") as f:
                    site_env = f.read()
                t.ok(rc == 0 and "SITE_FONT_FACE=Menlo-Regular\n" in site_env and "SITE_FONT_SIZE=13\n" in site_env,
                     "macOS: an installed face and points are written", out + site_env)
                rc, out, _ = spark("font", "Menlo-Regular", "99", extra=dict(off, SPARK_NO_APPLY="1"))
                t.ok(rc == 2 and "6 to 72" in out, "macOS: a size outside 6..72 points is refused", out)
                rc, out, _ = spark("font", "list", extra=off)
                t.ok("Menlo-Regular" in out and "the default" in out and "Nerd" not in out,
                     "macOS: spark font list names the faces every Mac ships, Menlo-Regular as the default", out)
            else:
                print("  skip macOS font guard: Spotlight indexing is off here")
        # quiet audio: both OSes, core, the key is the behaviour
        rc, out, _ = spark("quiet", "audio", "on", extra=off)
        with open(home + "/.config/spark/site.env") as f:
            site_env = f.read()
        t.ok(rc == 0 and "audio is quiet" in out and "SITE_QUIET_AUDIO=yes\n" in site_env,
             "spark quiet audio on writes the key and says so", out)
        rc, out, _ = spark("quiet", extra=off)
        t.ok(rc == 0 and "audio on" in out, "spark quiet shows the audio state with the others", out)
        rc, out, _ = spark("quiet", "audio", "off", extra=off)
        rc2, out2, _ = spark("quiet", "audio", extra=off)
        t.ok(rc == 0 and "audio is on" in out and rc2 == 0 and out2.strip().endswith("audio -- off"),
             "spark quiet audio off, and the one state shows", out + out2)
        rc, out, _ = spark("bootconfig", extra=off)
        t.ok(rc == 2 and out.startswith("spark: no command named bootconfig"),
             "spark bootconfig is no command any more (v1.3's stub is gone): a slip, exit 2", out)

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
            t.ok(rc == 0 and out.startswith("spark quiet login -- "), "spark quiet login shows its state (core, no gate)", out)
            rc, out, _ = spark("quiet", "login", "on", extra=off)
            t.ok(rc == 0 and "SITE_QUIET_LOGIN=yes" in open(home + "/.config/spark/site.env").read(),
                 "spark quiet login on writes the key (core, no gate)", out)
            spark("quiet", "login", "off", extra=off)
        rc, out, _ = spark("theme", "-h", extra=off)
        t.ok(rc == 0 and out.startswith("spark theme -- "), "spark theme -h signs (contract 8)", out)
        # the palette's runtime files, one writer: spark theme NAME writes
        # theme.env, console-colors (the VT escapes) and console-colors.rgb
        # (setvtrgb's three lines, for the boot unit); none removes theme.env
        # and turns both into the VGA sixteen
        rc, out, _ = spark("theme", "gruvbox-dark", extra=off)
        theme_env = open(home + "/.config/spark/theme.env").read()
        cc = open(home + "/.config/spark/console-colors").read()
        t.ok(rc == 0 and "THEME_BG=#282828\n" in theme_env and "THEME_BTOP" not in theme_env,
             "spark theme NAME writes theme.env from the palette (20 keys, no THEME_BTOP)", theme_env)
        t.ok(cc.startswith("\033]P0282828") and "\033]P9fb4934" in cc and "\033]Pfebdbb2" in cc,
             "console-colors holds the sixteen VT escapes, ansi 0-15 in hex", repr(cc))
        rgb = open(home + "/.config/spark/console-colors.rgb").read()
        from spark import theme as _theme_mod, config as _config_mod
        _pal = _config_mod.theme_palette("gruvbox-dark", REPO)
        t.ok(rgb == _theme_mod.vt_lines([_pal["THEME_ANSI_%d" % i] for i in range(16)]) and rgb.startswith("40,204,152,215,")
             and len(rgb.splitlines()) == 3 and all(len(l.split(",")) == 16 for l in rgb.splitlines()),
             "console-colors.rgb holds setvtrgb's three lines: red, green, blue of ansi 0-15", repr(rgb))
        rc, out, _ = spark("theme", "none", extra=off)
        t.ok(rc == 0 and not os.path.exists(home + "/.config/spark/theme.env")
             and open(home + "/.config/spark/console-colors").read().startswith("\033]P0000000\033]P1aa0000")
             and open(home + "/.config/spark/console-colors.rgb").read().splitlines()[0] == "0,170,0,170,0,170,0,170,85,255,85,255,85,255,85,255",
             "spark theme none removes theme.env and leaves the VGA sixteen in both console files", out)
        rc, out, _ = spark("theme", "nosuch", extra=off)
        t.ok(rc == 2 and out.startswith("spark theme -- "), "spark theme nosuch: usage, exit 2", out)

        # the client shape: spark client (state, URL, off); the check's client rows
        rc, out, _ = spark("client", extra=off)
        t.ok(rc == 0 and "not a client" in out and "SITE_PEER_AI_URL=unset" in out, "spark client: not a client", out)
        rc, out, _ = spark("client", "192.0.2.10:8081", extra=off)
        t.ok(rc == 2 and out.startswith("spark client -- URL is http://"), "spark client without a scheme is refused", out)
        rc, out, _ = spark("client", "http://192.0.2.10:8081/", extra=off)
        site_env = open(home + "/.config/spark/site.env").read()
        t.ok(rc == 0 and "SITE_PEER_AI_URL=http://192.0.2.10:8081\n" in site_env and "SITE_AI_MODEL=none\n" in site_env
             and "ember-token" not in out,
             "spark client URL writes the peer and none; no scp of any secret", out)
        rc, out, _ = spark("client", extra=off)
        t.ok(rc == 0 and "of http://192.0.2.10:8081" in out and "peer" in out and "account" in out,
             "spark client: the state, a client, the account row", out)
        rc, outp, _ = spark("check", "--porcelain", "--fresh", extra=dict(off, SITE_PEER_AI_URL="http://192.0.2.10:8081"))
        t.ok(all(re.search(r"^\w+\tna\t%s\ta client of 192.0.2.10:8081" % r, outp, re.M) for r in ("engine", "services", "watchdog", "ai", "serve", "forge")),
             "spark check as a client: engine, services, watchdog, ai, serve, forge are na", outp)
        # a client's model table is the peer's, never this machine's RAM;
        # a choice made here is refused (it would make a server of a client)
        cl = dict(off, SPARK_MEM_TOTAL_GB="24")
        rc, out, _ = spark("model", extra=cl)
        t.ok(rc == 0 and out.splitlines()[0].startswith("spark model") and "a client of http://192.0.2.10:8081" in out.splitlines()[0]
             and "24 GB" not in out and "budget" not in out.splitlines()[0],
             "spark model on a client (peer down): no local RAM, no budget, the peer named", out)
        crow = [ln for ln in out.splitlines() if re.match(r"^  [ *+][ u] \S+ +\d+\.\d GB ", ln)]
        t.ok(crow and not any("tok/s" in ln or "too big" in ln for ln in crow), "a client's rows carry no verdict", out)
        rc, outb, _ = spark("model", "budget", extra=cl)
        t.ok(rc == 0 and outb == out, "spark model budget on a client prints the same table, no local percent", outb)
        for verb in (("model", "budget", "40"), ("model", "qwen3-1-7b"), ("model", "auto"), ("model", "rm", "qwen3-1-7b"),
                     ("ember", "qwen3-1-7b"), ("ember", "auto")):
            rc, outv, _ = spark(*verb, extra=cl)
            t.ok(rc == 2 and "serves nothing" in outv and "spark client off" in outv and outv.startswith("spark " + verb[0]),
                 "spark %s on a client is refused with the one line" % " ".join(verb), outv)
        site_env = open(home + "/.config/spark/site.env").read()
        t.ok("SITE_AI_MODEL=none\n" in site_env and "SITE_AI_BUDGET=40" not in site_env and "SITE_EMBER_MODEL=qwen3" not in site_env,
             "the refusals wrote nothing", site_env)
        rc, out, _ = spark("client", "off", extra=off)
        site_env = open(home + "/.config/spark/site.env").read()
        t.ok(rc == 0 and "SITE_AI_MODEL=auto\n" in site_env and "the other machine stays first" in out,
             "spark client off hands the model choice back to auto", out)
        rc, out, _ = spark("client", "-h")
        t.ok(rc == 0 and out.splitlines()[0] == "spark client -- a client of another machine's server",
             "spark client -h signs (contract 8)", out)

        # spark setup: the guided first run, non-interactive, nothing applied
        os.remove(home + "/.config/spark/site.env")
        rc, out, _ = spark("setup", "-h")
        t.ok(rc == 0 and out.splitlines()[0] == "spark setup -- choose the model this machine can run",
             "spark setup -h signs (contract 8)", out)
        rc, out, _ = spark(extra=off)
        t.ok(rc == 0 and "'s AI on" in out, "bare spark with no site.env, not a tty: the status (the offer is tty-only)", out)
        for stale in ("theme.env", "console-colors"):   # earlier cases left theirs
            try:
                os.remove(home + "/.config/spark/" + stale)
            except OSError:
                pass
        rc, out, err = spark("setup", "--yes", "--no-serve", "--model", "none", extra=off)
        site_env = open(home + "/.config/spark/site.env").read()
        t.ok(rc == 0 and err == "", "spark setup --yes --no-serve --model none exits 0", out + err)
        t.ok(re.search(r"^SITE_NAME=\S", site_env, re.M) and re.search(r"^SITE_USER=\S", site_env, re.M)
             and "SITE_AI_MODEL=none\n" in site_env,
             "setup wrote SITE_NAME, SITE_USER, SITE_AI_MODEL=none", site_env)
        t.ok("SITE_THEME=none\n" in site_env and "theme [" not in out,
             "setup never asks the palette: none is written unasked", site_env + out)
        t.ok(not os.path.exists(home + "/.config/spark/theme.env")
             and not os.path.exists(home + "/.config/spark/console-colors"),
             "setup applies no palette: the machine looks untouched (spark theme paints)", out)
        rc, out, _ = spark("setup", "--yes", "--no-serve", "--model", "none", "--theme", "nosuch", extra=off)
        t.ok(rc == 2 and "no palette named nosuch" in out and "none" in out,
             "setup --theme nosuch exits 2 naming the palettes", out)
        rc, out, _ = spark("setup", "--yes", "--no-serve", "--model", "none", "--theme", "none", extra=off)
        t.ok(rc == 0 and "SITE_THEME=none\n" in open(home + "/.config/spark/site.env").read(),
             "setup --theme none writes none (the flag is how you say no)", out)
        t.ok("\u2588" in out and "GB for models" in out and "SITE_AI_MODEL=none" in out and "open a new shell" in out
             and "spark ember NAME adds a chat model" in out,
             "setup printed the logo, the table header, the model line and the closing block", out)
        t.ok("no model chosen" in out, "setup with none says how to choose later", out)
        t.ok("skip   account      no model here" in out and "the token, shown once" not in out
             and "spark user login NAME" in out,
             "setup with no model mints no account and prints no token (a client never mints)", out)
        # a login with a token this machine's store does not hold names the
        # remedy; SPARK_YES=1 answers the remove question (a script's form)
        _xdg5 = {"XDG_STATE_HOME": home + "/.local/state-users"}
        rc, out, _ = spark("user", "add", "ana", "--show-token", "--no-qr", extra=_xdg5)
        t.ok(rc == 0 and "ok     user         ana" in out, "spark user add ana in a fresh state dir", out)
        rc, out, _ = spark("user", "login", "bo", stdin="not-anas-token\n", extra=_xdg5)
        t.ok(rc == 1 and "this machine's store is ana's" in out and "spark user remove ana frees it" in out,
             "user login with a foreign token names the remedy (spark user remove NAME)", out)
        rc, out, _ = spark("user", "remove", "ana", extra=_xdg5)
        t.ok(rc == 0 and "spark user: kept" in out and os.path.isdir(home + "/.local/state-users/spark/users/ana"),
             "user remove without a yes keeps the user", out)
        rc, out, _ = spark("user", "remove", "ana", extra=dict(_xdg5, SPARK_YES="1"))
        t.ok(rc == 0 and "ana removed" in out and not os.path.exists(home + "/.local/state-users/spark/users/ana"),
             "SPARK_YES=1 answers the remove question", out)
        # a client with no login answers and keeps nothing: the FORGE it
        # answers from is the account authority, nothing is minted here
        _xdg6 = {"XDG_STATE_HOME": home + "/.local/state-client", "SITE_AI_MODEL": "none", "SITE_PEER_AI_URL": url}
        rc, out, err = spark("chat", "count", extra=_xdg6)
        t.ok(rc == 0 and out.strip() and not os.path.exists(home + "/.local/state-client/spark/users")
             and not os.path.exists(home + "/.local/state-client/spark/account"),
             "a client with no login answers and mints nothing (a client never mints)", out + err)
        # the headless render fact reads the node itself: open to every user
        # (Void: 0666, group video, no render group) is the GPU from boot;
        # a node closed to others needs its owning group
        from spark import site as _site
        _node = os.path.join(home, "renderD128")
        open(_node, "w").close()
        os.chmod(_node, 0o666)
        _f = _site.render_fact(_node)
        t.ok(_f[0] == "render node" and _f[1] is True and "open to every user" in _f[2],
             "headless: a render node open to every user needs no group (Void)", repr(_f))
        os.chmod(_node, 0o600)
        _f = _site.render_fact(_node)
        t.ok(_f[0].endswith(" group") and _f[0] != "render node",
             "headless: a closed render node names the group that owns it", repr(_f))
        # a client whose box was reinstalled: the box minted a new token,
        # and the login re-locks this machine's sealed store under it,
        # threads kept; the machine that serves still refuses a pasted one
        _xdg7 = {"XDG_STATE_HOME": home + "/.local/state-relock"}
        rc, out, _ = spark("user", "add", "ana", "--show-token", "--no-qr", extra=_xdg7)
        old = out.split("shown once, never stored; it is the only key:\n", 1)[-1].split()[0]
        rc, out, _ = spark("user", "login", "ana", stdin=old + "\n", extra=_xdg7)
        t.ok(rc == 0 and "this machine is ana" in out, "the old token logs ana in", out)
        rc, out, _ = spark("user", "login", "ana", stdin="the-new-boxs-token\n", extra=_xdg7)
        t.ok(rc == 1 and "sealed threads now open" not in out,
             "the machine that serves refuses a pasted token it never minted", out)
        _cl7 = dict(_xdg7, SITE_AI_MODEL="none", SITE_PEER_AI_URL=url)
        rc, out, _ = spark("user", "login", "ana", stdin="a-typo\n", extra=_cl7)
        t.ok(rc == 1 and "did not accept that token as ana -- the store stays as it is" in out,
             "a client re-locks nothing the box does not accept", out)
        rc, out, _ = spark("user", "login", "ana", stdin="the-new-boxs-token\n", extra=_cl7)
        t.ok(rc == 0 and "ana's sealed threads now open with the new token" in out
             and "this machine is ana" in out,
             "a client re-locks its store to the reinstalled box's token", out)
        rc, out, _ = spark("user", "login", "ana", stdin=old + "\n", extra=_cl7)
        t.ok(rc == 1, "after the re-lock the old token opens nothing", out)
        rc, out, _ = spark("user", "login", "ana", stdin="the-new-boxs-token\n", extra=_cl7)
        t.ok(rc == 0 and "sealed threads now open" not in out and "this machine is ana" in out,
             "the new token opens the store as its own", out)
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

        # your own palettes: ~/.config/spark/themes/<name>.env, found by
        # config.theme_path,
        # listed as yours, and winning over the repository's on a clash
        mine_dir = home + "/.config/spark/themes"
        os.makedirs(mine_dir, exist_ok=True)
        with open(os.path.join(REPO, "themes", "nord.env")) as f:
            mine = f.read().replace("#2e3440", "#101010")
        with open(mine_dir + "/mine.env", "w") as f:
            f.write(mine)
        rc, out, _ = spark("theme")
        t.ok(rc == 0 and "mine" in out and "yours: ~/.config/spark/themes/mine.env" in out,
             "theme: a palette in ~/.config/spark/themes is listed as yours", out)
        rc, out, err = spark("theme", "mine", extra={"SPARK_NO_APPLY": "1"})
        with open(home + "/.config/spark/theme.env") as f:
            theme_env = f.read()
        t.ok(rc == 0 and "THEME_BG=#101010" in theme_env, "theme mine: chosen and written from your file", out + err + theme_env)
        with open(mine_dir + "/nord.env", "w") as f:
            f.write(mine.replace("#101010", "#202020"))
        rc, out, err = spark("theme", "nord", extra={"SPARK_NO_APPLY": "1"})
        with open(home + "/.config/spark/theme.env") as f:
            theme_env = f.read()
        t.ok(rc == 0 and "THEME_BG=#202020" in theme_env, "theme: yours wins over the repository's on a name clash", out + err)
        os.remove(mine_dir + "/nord.env")
        rc, out, _ = spark("mine")
        t.ok(rc == 2 and "is a palette -- spark theme mine" in out, "a bare palette name of yours is a slip, not a question", out)
        # spark uninstall: signed, shows and never mutates without the word;
        # SPARK_NO_APPLY = the plan only (the real run is tests/uninstall_test.sh)
        rc, out, _ = spark("uninstall", "-h")
        t.ok(rc == 0 and out.splitlines()[0] == "spark uninstall -- remove spark from this machine: shows first, then asks yes",
             "spark uninstall -h signs (contract 8)", out)
        snap = sorted(os.listdir(home + "/.config/spark"))
        rc, out, _ = spark("uninstall", extra={"SPARK_NO_APPLY": "1"})
        t.ok(rc == 0 and "the plan" in out and not any(l.startswith("ok ") for l in out.splitlines())
             and sorted(os.listdir(home + "/.config/spark")) == snap,
             "spark uninstall under SPARK_NO_APPLY prints the plan and changes nothing", out[:300])
        rc, out, _ = spark("uninstall", "--nope")
        t.ok(rc == 2 and out.startswith("spark uninstall -- "), "spark uninstall --nope: usage, exit 2", out)
        rc, out, _ = spark("uninstall")
        t.ok(rc == 2 and "not a terminal: spark uninstall --yes runs it" in out,
             "spark uninstall at a non-terminal without --yes: the plan, then refused, exit 2", out[-200:])

        # WSL 2: the OS fact from the kernel line, pinned by SPARK_PROC_VERSION
        # (both OSes, in-process twin); the verbs that own the console and GRUB
        # refuse there, the status names it (Linux, through the CLI)
        with open(home + "/version-wsl", "w") as f:
            f.write("Linux version 6.6.87.2-microsoft-standard-WSL2 (root@w) #1 SMP PREEMPT_DYNAMIC\n")
        with open(home + "/version-plain", "w") as f:
            f.write("Linux version 6.12.0-amd64 (debian-kernel) #1 SMP PREEMPT_DYNAMIC Debian\n")
        wsl_twin = ("import sys; sys.path.insert(0, %r); import spark; spark.IS_MAC = False; "
                    "print(spark.is_wsl(), spark.os_pretty().endswith(' on WSL 2'))" % os.path.join(REPO, "lib"))

        def wsl_fact(path):
            p = subprocess.run([sys.executable, "-c", wsl_twin], capture_output=True, text=True,
                               env=dict(env, SPARK_PROC_VERSION=path), timeout=30)
            return p.stdout.strip() or p.stderr.strip()
        t.ok(wsl_fact(home + "/version-wsl") == "True True", "is_wsl: a kernel line naming microsoft, and os_pretty says on WSL 2", wsl_fact(home + "/version-wsl"))
        t.ok(wsl_fact(home + "/version-plain") == "False False", "is_wsl: a plain kernel line is not WSL", wsl_fact(home + "/version-plain"))
        t.ok(wsl_fact(home + "/version-none") == "False False", "is_wsl: no file at all is not WSL", wsl_fact(home + "/version-none"))
        # the package family from os-release, pinned by SPARK_OS_RELEASE (both
        # OSes, in-process twin): ID first, then ID_LIKE's words; unknown is ''
        for name, body in (("arch", 'ID=arch\nPRETTY_NAME="Arch Linux"\n'),
                           ("ubuntu", 'ID=ubuntu\nID_LIKE=debian\nPRETTY_NAME="Ubuntu 24.04 LTS"\n'),
                           ("manjaro", 'ID=manjaro\nID_LIKE=arch\n'),
                           ("fedora", 'ID=fedora\nPRETTY_NAME="Fedora Linux 42"\n')):
            with open(home + "/os-release-" + name, "w") as f:
                f.write(body)
        distro_twin = ("import sys; sys.path.insert(0, %r); import spark; spark.IS_MAC = False; "
                       "print(repr(spark.distro()), spark.os_pretty())" % os.path.join(REPO, "lib"))

        def distro_fact(path):
            p = subprocess.run([sys.executable, "-c", distro_twin], capture_output=True, text=True,
                               env=dict(env, SPARK_OS_RELEASE=path, SPARK_PROC_VERSION=home + "/version-plain"), timeout=30)
            return p.stdout.strip() or p.stderr.strip()
        t.ok(distro_fact(home + "/os-release-arch") == "'arch' Arch Linux", "distro: ID=arch is arch, and os_pretty reads the file's PRETTY_NAME", distro_fact(home + "/os-release-arch"))
        t.ok(distro_fact(home + "/os-release-ubuntu") == "'debian' Ubuntu 24.04 LTS", "distro: ID=ubuntu ID_LIKE=debian is debian", distro_fact(home + "/os-release-ubuntu"))
        t.ok(distro_fact(home + "/os-release-manjaro").startswith("'arch' "), "distro: ID=manjaro ID_LIKE=arch is arch", distro_fact(home + "/os-release-manjaro"))
        t.ok(distro_fact(home + "/os-release-fedora") == "'' Fedora Linux 42", "distro: an unknown family is '', never a guess", distro_fact(home + "/os-release-fedora"))
        t.ok(distro_fact(home + "/os-release-none").startswith("'' Linux "), "distro: no file at all is '', and os_pretty falls back to the kernel", distro_fact(home + "/os-release-none"))
        # bootstrap asks the same code through lib/spark/facts.py (the one
        # home, no sh twin): its DISTRO line honours the same fixture
        for name, want in (("arch", "arch"), ("ubuntu", "debian"), ("manjaro", "arch"), ("fedora", "")):
            p = subprocess.run([sys.executable, os.path.join(REPO, "lib", "spark", "facts.py")],
                               capture_output=True, text=True, timeout=30,
                               env=dict(os.environ, SPARK_OS_RELEASE=home + "/os-release-" + name,
                                        HOME=home, SPARK_MEM_TOTAL_GB="16"))
            got = re.search(r"^DISTRO='?([^'\n]*?)'?$", p.stdout, re.M)
            t.ok(got is not None and got.group(1) == want,
                 "facts.py DISTRO: %s -> %r (what bootstrap eval's)" % (name, want), p.stdout + p.stderr)
        # Void (v1.50), the third family: ID="void" is quoted in Void's
        # os-release; the init is told by /etc/runit (SPARK_ETC_RUNIT), a
        # booted runit by /var/service (SPARK_VAR_SERVICE), musl by its
        # loader (SPARK_LD_MUSL). In-process twins on both OSes: SPARK_OS=
        # Linux pins the OS the way bootstrap hands facts.py its uname view
        with open(home + "/os-release-void", "w") as f:
            f.write('ID="void"\nPRETTY_NAME="Void Linux"\n')
        os.makedirs(home + "/runit", exist_ok=True)
        os.makedirs(home + "/void-service", exist_ok=True)
        with open(home + "/ld-musl-x86_64.so.1", "w") as f:
            f.write("")
        void_env = dict(env, SPARK_OS="Linux", SPARK_OS_RELEASE=home + "/os-release-void", SPARK_PROC_VERSION=home + "/version-plain",
                        SPARK_REPO=REPO, SPARK_ETC_RUNIT=home + "/runit", SPARK_VAR_SERVICE=home + "/no-service",
                        SPARK_LD_MUSL=home + "/no-ld-musl-*.so.1")

        def twin(code, **more):
            p = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, %r)\n%s" % (os.path.join(REPO, "lib"), code)],
                               capture_output=True, text=True, env=dict(void_env, **more), timeout=60)
            return p.stdout.strip() if p.returncode == 0 else "rc %d: %s%s" % (p.returncode, p.stdout, p.stderr)
        _fact = "import spark; print(repr(spark.distro()), spark.os_pretty(), spark.init_shape(), spark.runit_live(), spark.is_musl())"
        t.ok(twin(_fact) == "'void' Void Linux runit False False",
             "void: ID=\"void\" (quoted) is void, os_pretty says Void Linux, /etc/runit says runit, no /var/service is not live, no musl loader", twin(_fact))
        t.ok(twin(_fact, SPARK_VAR_SERVICE=home + "/void-service") == "'void' Void Linux runit True False",
             "void: a /var/service dir says runit is live", twin(_fact, SPARK_VAR_SERVICE=home + "/void-service"))
        t.ok(twin(_fact, SPARK_ETC_RUNIT=home + "/no-runit") == "'void' Void Linux systemd False False",
             "void: without /etc/runit the init is systemd (the assumption every other Linux had)", twin(_fact, SPARK_ETC_RUNIT=home + "/no-runit"))
        t.ok(twin(_fact, SPARK_LD_MUSL=home + "/ld-musl-*.so.1") == "'void' Void Linux runit False True",
             "void: a loader at the musl pattern is musl", twin(_fact, SPARK_LD_MUSL=home + "/ld-musl-*.so.1"))
        t.ok(twin("from spark import engine; print(repr(engine.flavour('Linux', 'x86_64', 'cpu')))", SPARK_LD_MUSL=home + "/ld-musl-*.so.1") == "('', '')"
             and twin("from spark import engine; print(engine.flavour('Linux', 'x86_64', 'cpu')[0])") == "ubuntu-x64",
             "void: on musl the engine pins nothing (the tarballs are glibc builds); glibc keeps its pin")
        from spark import init_shape as _init_shape
        t.ok(_init_shape() == ("launchd" if sys.platform == "darwin" else ("runit" if os.path.isdir("/etc/runit") else "systemd")),
             "init_shape unseamed: launchd on this Mac; on Linux runit only where /etc/runit is a dir, else systemd", _init_shape())
        # bootstrap's view of the same, through facts.py: INIT, RUNIT_LIVE
        # and VAR_SERVICE beside DISTRO
        p = subprocess.run([sys.executable, os.path.join(REPO, "lib", "spark", "facts.py")], capture_output=True, text=True, timeout=30,
                           env=dict(os.environ, SPARK_OS_RELEASE=home + "/os-release-void", SPARK_ETC_RUNIT=home + "/runit",
                                    SPARK_VAR_SERVICE=home + "/no-service", HOME=home, SPARK_MEM_TOTAL_GB="16"))
        t.ok(re.search(r"^DISTRO=void$", p.stdout, re.M) and re.search(r"^INIT=runit$", p.stdout, re.M)
             and re.search(r"^RUNIT_LIVE=0$", p.stdout, re.M) and re.search(r"^VAR_SERVICE='?%s'?$" % re.escape(home + "/no-service"), p.stdout, re.M),
             "facts.py under void: DISTRO=void, INIT=runit, RUNIT_LIVE=0 and VAR_SERVICE (what bootstrap eval's)", p.stdout + p.stderr)
        # the package family's verbs under void: xbps, its install, upgrade
        # and removal lines, and the tools' xbps column (fdfind is fd there,
        # batcat is bat; a tool spark does not know is '')
        _pk = ("from spark import packages as p; print(p.manager(), '|', p.install_line(['fd']), '|', p.upgrade_line(), '|', "
               "' '.join(p.remove_argv(['fd'])), '|', p.remove_line(['fd']), '|', p.package_for('fd'), p.package_for('fdfind'), "
               "p.package_for('batcat'), repr(p.package_for('nosuch')))")
        t.ok(twin(_pk) == "xbps | sudo xbps-install -Sy fd | sudo xbps-install -Su | xbps-remove -y fd | sudo xbps-remove -y fd | fd fd bat ''",
             "void: manager xbps, install through xbps-install -Sy, upgrade -Su, removal xbps-remove -y, the tools' xbps column", twin(_pk))
        # the console's third shape: rc.conf beside /etc/runit is rcconf and
        # the font file; rc.conf without runit is no shape (by mechanism, not
        # by file); quiet boot on a void without GRUB is the Void line either way
        with open(home + "/rc.conf", "w") as f:
            f.write('#KEYMAP="us"\nFONT="Terminus"\n')
        rcconf = dict(SPARK_ETC_CONSOLE_SETUP=home + "/no-console-setup", SPARK_ETC_VCONSOLE=home + "/no-vconsole", SPARK_ETC_RCCONF=home + "/rc.conf",
                      SPARK_ETC_DEFAULT_GRUB=home + "/no-default-grub")
        _shape = "from spark import site; print(site.console_shape() or '-', site.font_file(), site.no_console_font() or '-', '|', site.no_grub())"
        _void_no_boot = "no GRUB on this Void: its boot loader is left alone"
        t.ok(twin(_shape, **rcconf) == "rcconf %s/rc.conf - | %s" % (home, _void_no_boot),
             "void: rc.conf beside /etc/runit is the rcconf shape, the font file is rc.conf, quiet boot is refused with the Void line", twin(_shape, **rcconf))
        t.ok(twin(_shape, SPARK_ETC_RUNIT=home + "/no-runit", **rcconf)
             == "- %s/no-vconsole no console-setup, vconsole.conf or rc.conf here: the console font is not spark's to set | %s" % (home, _void_no_boot),
             "rc.conf without /etc/runit is no shape: the font is not spark's to set there", twin(_shape, SPARK_ETC_RUNIT=home + "/no-runit", **rcconf))
        # the service manager's verbs on runit, against an sv stub that logs
        # its argv and answers status from the dir the way runsv leaves it
        # (a supervise/ dir and no down file is run:, a down file is down:,
        # no supervise/ is fail:); the dir is the unit, its down file the
        # disable, a missing dir absent
        os.makedirs(home + "/svbin", exist_ok=True)
        with open(home + "/svbin/sv", "w") as f:
            f.write('#!/bin/sh\necho "sv $*" >> "${SV_LOG:-/dev/null}"\ncase $1 in\n'
                    '    status) if [ ! -d "$2/supervise" ]; then echo "fail: $2: runsv not running"; exit 1\n'
                    '            elif [ -f "$2/down" ]; then echo "down: $2: 1s, normally up"\n'
                    '            else echo "run: $2: (pid 1) 1s"; fi ;;\n'
                    '    *) [ -z "${SV_FAIL:-}" ] || { echo "fail: $2: runsv not running"; exit 1; } ;;\n'
                    'esac\nexit 0\n')
        os.chmod(home + "/svbin/sv", 0o755)
        vhome = home + "/void-home"
        vd = vhome + "/.config/spark/sv/spark-serve"
        _eng = r'''
import os
from spark import engine
d = engine.service_dir("serve")
print("dir", d)
print("name", engine.unit_name("serve"), engine.unit_name("check"))
print("parse", engine.parse_sv_status("run: /x: (pid 1) 1s"), engine.parse_sv_status("down: /x: 1s, normally up"),
      engine.parse_sv_status("fail: /x: runsv not running"), engine.parse_sv_status(""))
print("absent", engine.service_state(None, "serve"), engine.sv_status("serve"))
os.makedirs(d)
print("loaded", engine.service_state(None, "serve"))
open(os.path.join(d, "down"), "w").close()
print("disabled", engine.service_state(None, "serve"))
os.remove(os.path.join(d, "down"))
print("stop", engine.service_stop(False, "serve"), "|", os.path.exists(os.path.join(d, "down")))
print("stopnr", engine.service_stop(True, "serve"), "|", os.path.exists(os.path.join(d, "down")))
os.makedirs(os.path.join(d, "supervise"))
print("status", engine.sv_status("serve"))
os.remove(os.path.join(d, "down"))
print("status", engine.sv_status("serve"))
print("kick", engine.kickstart(None, "serve"), engine.kickstart(None, "serve", restart=True))
os.environ["SV_FAIL"] = "1"
print("kickfail", engine.kickstart(None, "serve"))
print("restart", engine.restart_line("serve"), "|", engine.restart_line("check"))
'''
        _svlog = home + "/sv-twin.log"
        got = twin(_eng, HOME=vhome, XDG_CONFIG_HOME=vhome + "/.config", XDG_STATE_HOME=vhome + "/.local/state",
                   PATH=home + "/svbin:" + env["PATH"], SV_LOG=_svlog)
        want = "\n".join([
            "dir " + vd,
            "name spark-serve spark-check",
            "parse run down absent absent",
            "absent absent ('absent', '')",
            "loaded loaded",
            "disabled disabled",
            "stop sv up ~/.config/spark/sv/spark-serve | False",
            "stopnr rm ~/.config/spark/sv/spark-serve/down; sv up ~/.config/spark/sv/spark-serve | True",
            "status ('down', 'down: %s: 1s, normally up')" % vd,
            "status ('run', 'run: %s: (pid 1) 1s')" % vd,
            "kick True True",
            "todo   serve        sv up spark-serve failed: fail: %s: runsv not running" % vd,
            "kickfail False",
            "restart sv restart ~/.config/spark/sv/spark-serve; tail ~/.local/state/spark/log/spark-serve/current | "
            "sv restart ~/.config/spark/sv/spark-check; tail ~/.local/state/spark/log/spark-check/current",
        ])
        t.ok(got == want, "engine on runit: the dir is the unit, down is the disable, sv status's three words, the undo lines, "
             "sv up/restart through kickstart and its todo, restart_line per unit",
             "\n".join(l for l in got.splitlines() if l not in want.splitlines()) or got)
        try:
            with open(_svlog) as f:
                _svcalls = f.read().splitlines()
        except OSError:
            _svcalls = []
        t.ok(_svcalls == ["sv down " + vd, "sv down " + vd, "sv status " + vd, "sv status " + vd, "sv up " + vd, "sv restart " + vd, "sv up " + vd],
             "engine on runit: sv is asked by the dir's path -- down twice (a stop, a stop with the down file), status, up, restart, up", str(_svcalls))
        if sys.platform != "darwin":
            wsl = dict(SPARK_PROC_VERSION=home + "/version-wsl", SPARK_NO_APPLY="1")
            rc, out, _ = spark("font", extra=wsl)
            t.ok(rc == 0 and out.strip() == "spark font -- no console on WSL 2: the font lives in Windows Terminal's settings",
                 "WSL 2: spark font shows the one line (contract 8), exit 0", out)
            before = open(home + "/.config/spark/site.env").read()
            rc, out, _ = spark("font", "Terminus", "16x32", extra=wsl)
            t.ok(rc == 2 and "no console on WSL 2" in out and open(home + "/.config/spark/site.env").read() == before,
                 "WSL 2: spark font FACE SIZE refuses with the same line, exit 2, site.env untouched", "%d %s" % (rc, out))
            rc, out, _ = spark("quiet", "boot", "on", extra=wsl)
            t.ok(rc == 2 and out.strip() == "spark quiet boot -- no GRUB on WSL 2: Windows boots it",
                 "WSL 2: spark quiet boot on refuses: no GRUB", out)
            rc, out, _ = spark("headless", "on", extra=wsl)
            t.ok(rc == 2 and "WSL 2 stops with its last window" in out and "SITE_HEADLESS=yes" not in open(home + "/.config/spark/site.env").read(),
                 "WSL 2: spark headless on refuses: it cannot stay on", out)
            rc, out, _ = spark("status", extra=wsl)
            t.ok("(WSL 2)" in out, "WSL 2: the status line names it", out.splitlines()[0] if out else "")
            # Arch (ID=arch in os-release): the console font is by mechanism
            # -- vconsole.conf's FONT= names a kbd font file, its size in the
            # file's own header (PSF1 and PSF2, gzip or plain); the fixture
            # holds one of each, and no console-setup file
            arch = dict(SPARK_OS_RELEASE=home + "/os-release-arch", SPARK_PROC_VERSION=home + "/version-plain", SPARK_NO_APPLY="1",
                        SPARK_ETC_CONSOLE_SETUP=home + "/no-console-setup", SPARK_ETC_VCONSOLE=home + "/vconsole.conf",
                        SPARK_CONSOLEFONTS_DIR=home + "/consolefonts")
            import gzip as _gzip
            import struct as _struct
            os.makedirs(home + "/consolefonts", exist_ok=True)
            with open(home + "/vconsole.conf", "w") as f:
                f.write("KEYMAP=us\nFONT=default8x16\n")
            psf2 = b"\x72\xb5\x4a\x86" + _struct.pack("<IIIIIII", 0, 32, 0, 256, 16, 16, 8) + b"\0" * 16   # 8x16
            with _gzip.open(home + "/consolefonts/fixture16.psfu.gz", "wb") as f:
                f.write(psf2)
            with open(home + "/consolefonts/old12.psf", "wb") as f:
                f.write(b"\x36\x04\x00\x0c" + b"\0" * 28)                              # PSF1, 8x12
            with open(home + "/consolefonts/README", "w") as f:
                f.write("not a font\n")
            from spark import site as _site3
            t.ok(_site3.psf_size(home + "/consolefonts/fixture16.psfu.gz") == "8x16" and _site3.psf_size(home + "/consolefonts/old12.psf") == "8x12"
                 and _site3.psf_size(home + "/consolefonts/README") == "",
                 "psf_size: a PSF2 (gzip) and a PSF1 (plain) header say their cell; anything else says nothing")
            rc, out, _ = spark("font", "list", extra=arch)
            t.ok(rc == 0 and "  fixture16                8x16" in out and "  old12                    8x12" in out and "README" not in out
                 and "vconsole.conf" in out,
                 "Arch: spark font list prints the kbd fonts with the size their headers say, and names vconsole.conf", out)
            rc, out, _ = spark("font", "fixture16", "8x16", extra=arch)
            site_env = open(home + "/.config/spark/site.env").read()
            t.ok(rc == 0 and "SITE_FONT_FACE=fixture16\n" in site_env and "SITE_FONT_SIZE=8x16\n" in site_env,
                 "Arch: spark font FACE SIZE sets both keys for a font the files hold", "%d %s" % (rc, out))
            rc, out, _ = spark("font", extra=arch)
            t.ok(rc == 0 and out.strip() == "spark font -- console: fixture16 8x16 (%s/vconsole.conf)" % home,
                 "Arch: spark font shows the choice and the file it lands in", out)
            before = site_env
            rc, out, _ = spark("font", "fixture16", "16x32", extra=arch)
            t.ok(rc == 2 and "fixture16 comes in 8x16, not 16x32" in out and open(home + "/.config/spark/site.env").read() == before,
                 "Arch: a size the file does not have is refused, naming the one it has; site.env untouched", "%d %s" % (rc, out))
            rc, out, _ = spark("font", "nosuch", "8x16", extra=arch)
            t.ok(rc == 2 and "no console font named nosuch" in out, "Arch: a font the files lack is refused", out)
            rc, out, _ = spark("font", "none", extra=arch)
            t.ok(rc == 0 and "SITE_FONT_FACE=\n" in open(home + "/.config/spark/site.env").read(), "Arch: spark font none clears the keys", out)
            # neither file: not spark's to set, one signed line (contract 8)
            bare = dict(arch, SPARK_ETC_VCONSOLE=home + "/no-vconsole")
            rc, out, _ = spark("font", extra=bare)
            t.ok(rc == 0 and out.strip() == "spark font -- no console-setup, vconsole.conf or rc.conf here: the console font is not spark's to set",
                 "no console file: spark font shows the one line (contract 8), exit 0", out)
            before = open(home + "/.config/spark/site.env").read()
            rc, out, _ = spark("font", "fixture16", "8x16", extra=bare)
            t.ok(rc == 2 and "not spark's to set" in out and open(home + "/.config/spark/site.env").read() == before,
                 "no console file: spark font FACE SIZE refuses with the same line, exit 2, site.env untouched", "%d %s" % (rc, out))
            # no UKI preset (the dir is pinned empty): the kernel line is the
            # boot loader's, the verb refuses in one signed line
            arch["SPARK_ETC_MKINITCPIO_D"] = home + "/no-mkinitcpio.d"
            rc, out, _ = spark("quiet", "boot", "on", extra=arch)
            t.ok(rc == 2 and out.strip() == "spark quiet boot -- no UKI on this Arch: the kernel line is the boot loader's "
                 "(a loader entry's options line, or GRUB_CMDLINE_LINUX_DEFAULT then grub-mkconfig)",
                 "Arch without a UKI: spark quiet boot on refuses: the kernel line is the boot loader's", out)
            # a Unified Kernel Image (a preset's default_uki=): the verb is
            # real -- the key is set (SPARK_NO_APPLY keeps bootstrap off)
            os.makedirs(home + "/mkinitcpio.d", exist_ok=True)
            with open(home + "/mkinitcpio.d/linux.preset", "w") as f:
                f.write('ALL_kver="/boot/vmlinuz-linux"\nPRESETS=(\'default\')\ndefault_uki="/boot/EFI/Linux/arch-linux.efi"\n'
                        'default_options="--splash /usr/share/systemd/bootctl/splash-arch.bmp"\n')
            uki = dict(arch, SPARK_ETC_MKINITCPIO_D=home + "/mkinitcpio.d")
            rc, out, _ = spark("quiet", "boot", "on", extra=uki)
            t.ok(rc == 0 and "SITE_QUIET_BOOT=yes" in open(home + "/.config/spark/site.env").read(),
                 "Arch with a UKI: spark quiet boot on sets the key (the cmdline.d drop-in is spark's there)", "%d %s" % (rc, out))
            rc, out, _ = spark("quiet", "boot", extra=uki)
            t.ok(rc == 0 and out.strip() == "spark quiet boot -- on", "Arch with a UKI: spark quiet boot shows on", out)
            rc, out, _ = spark("quiet", "boot", "off", extra=uki)
            t.ok(rc == 0 and "SITE_QUIET_BOOT=no" in open(home + "/.config/spark/site.env").read(),
                 "Arch with a UKI: spark quiet boot off sets the key back", "%d %s" % (rc, out))
            rc, out, _ = spark("quiet", "login", "on", extra=arch)
            t.ok(rc == 0 and "SITE_QUIET_LOGIN=yes" in open(home + "/.config/spark/site.env").read(),
                 "Arch: spark quiet login on still sets the key (the motd is real there)", "%d %s" % (rc, out))
            rc, out, _ = spark("quiet", "login", "off", extra=arch)
            # Void (ID="void" in os-release, /etc/runit a dir, not booted):
            # without GRUB quiet boot refuses in one signed line and the
            # status says n/a and why; with GRUB it is real; quiet login is real; headless
            # is allowed (a Void box can be a brain) and its status reads
            # the supervisor fact, no linger or sleep; the console font is
            # rc.conf's FONT=, named on every line
            void = dict(SPARK_OS_RELEASE=home + "/os-release-void", SPARK_PROC_VERSION=home + "/version-plain", SPARK_NO_APPLY="1",
                        SPARK_ETC_CONSOLE_SETUP=home + "/no-console-setup", SPARK_ETC_VCONSOLE=home + "/no-vconsole",
                        SPARK_ETC_RCCONF=home + "/rc.conf", SPARK_ETC_RUNIT=home + "/runit", SPARK_VAR_SERVICE=home + "/no-service",
                        SPARK_CONSOLEFONTS_DIR=home + "/consolefonts", SPARK_ETC_DEFAULT_GRUB=home + "/no-default-grub")
            rc, out, _ = spark("quiet", "boot", "on", extra=void)
            t.ok(rc == 2 and out.strip() == "spark quiet boot -- " + _void_no_boot
                 and "SITE_QUIET_BOOT=yes" not in open(home + "/.config/spark/site.env").read(),
                 "Void: spark quiet boot on refuses with the Void line, exit 2, the key not set", "%d %s" % (rc, out))
            rc, out, _ = spark("quiet", "boot", extra=void)
            t.ok(rc == 0 and out.strip() == "spark quiet boot -- " + _void_no_boot,
                 "Void: bare spark quiet boot shows the same line, exit 0", out)
            rc, out, _ = spark("quiet", extra=void)
            t.ok(rc == 0 and "boot n/a," in out and "boot is n/a: " + _void_no_boot in out,
                 "Void: spark quiet's status says boot is n/a, and why on a line of its own", out)
            # with /etc/default/grub and update-grub the verb is real: the key
            # is set (bootstrap appends the marked lines), then set back
            os.makedirs(home + "/grub-bin", exist_ok=True)
            with open(home + "/grub-bin/update-grub", "w") as f:
                f.write("#!/bin/sh\nexit 0\n")
            os.chmod(home + "/grub-bin/update-grub", 0o755)
            with open(home + "/default-grub", "w") as f:
                f.write('GRUB_TIMEOUT=5\n')
            vgrub = dict(void, SPARK_ETC_DEFAULT_GRUB=home + "/default-grub",
                         PATH=home + "/grub-bin:" + os.environ.get("PATH", ""))
            rc, out, _ = spark("quiet", "boot", "on", extra=vgrub)
            t.ok(rc == 0 and "SITE_QUIET_BOOT=yes" in open(home + "/.config/spark/site.env").read(),
                 "Void with GRUB: spark quiet boot on sets the key", "%d %s" % (rc, out))
            rc, out, _ = spark("quiet", "boot", "off", extra=vgrub)
            rc, out, _ = spark("quiet", "login", "on", extra=void)
            t.ok(rc == 0 and "SITE_QUIET_LOGIN=yes" in open(home + "/.config/spark/site.env").read(),
                 "Void: spark quiet login on still sets the key (the motd is real there)", "%d %s" % (rc, out))
            rc, out, _ = spark("quiet", "login", "off", extra=void)
            rc, out, _ = spark("headless", "on", extra=void)
            t.ok(rc == 0 and "SITE_HEADLESS=yes" in open(home + "/.config/spark/site.env").read(),
                 "Void: spark headless on is allowed (a Void box can be a brain): the key is set", "%d %s" % (rc, out))
            rc, out, _ = spark("headless", extra=void)
            # the fact LABELS (the header says "never asleep": a word test
            # on the whole output would read sleep in it)
            t.ok(rc == 0 and "supervisor from boot" in out and "runit is not running here (a container)" in out
                 and not any(label in out for label in ("  linger ", " sleep masked ", " lid ignored ")),
                 "Void: spark headless status reads the supervisor fact; no linger, sleep or lid fact on runit", out)
            rc, out, _ = spark("headless", "off", extra=void)
            t.ok(rc == 0 and "SITE_HEADLESS=no" in open(home + "/.config/spark/site.env").read(), "Void: spark headless off sets the key back", "%d %s" % (rc, out))
            rc, out, _ = spark("font", "list", extra=void)
            t.ok(rc == 0 and "  fixture16                8x16" in out and "it lands in %s/rc.conf" % home in out,
                 "Void: spark font list prints the kbd fonts and names rc.conf as where a choice lands", out)
            rc, out, _ = spark("font", "fixture16", "8x16", extra=void)
            t.ok(rc == 0 and "SITE_FONT_FACE=fixture16\n" in open(home + "/.config/spark/site.env").read(),
                 "Void: spark font FACE SIZE sets the keys on the rcconf shape", "%d %s" % (rc, out))
            rc, out, _ = spark("font", extra=void)
            t.ok(rc == 0 and out.strip() == "spark font -- console: fixture16 8x16 (%s/rc.conf)" % home,
                 "Void: spark font shows the choice and rc.conf as its file", out)
            rc, out, _ = spark("font", "none", extra=void)
            rc, out, _ = spark("font", extra=void)
            t.ok(rc == 0 and out.strip() == "spark font -- console: not managed (SITE_FONT_FACE unset; %s/rc.conf keeps its font)" % home,
                 "Void: spark font none, then bare spark font names rc.conf as the file that keeps its font", out)

        # the egg (lib/spark/lua.py): the forest, headless through --sim, then a pty
        rc, out, _ = spark("lua", "--sim", "1", "auto")
        first = out.splitlines()[0] if out else ""
        t.ok(rc == 0 and first.startswith("zone ") and " over " in first, "lua --sim: one machine-readable line first", out)
        rc, out2, _ = spark("lua", "--sim", "1", "auto", extra={"XDG_STATE_HOME": home + "/.local/state-b",
                                                                 "XDG_CONFIG_HOME": home + "/.config-b"})
        t.ok(out2.splitlines()[0] == first, "lua --sim: the same seed gives the same numbers", out2)
        rc, out3, _ = spark("lua", "--sim", "1", "auto", "2026-09-26")
        t.ok(rc == 0 and out3.splitlines()[0] == first, "lua --sim: the moon changes the light, not the numbers", out3)
        # the pilot takes star 1 on every seed, and wins some seed
        wins, star1 = [], []
        from spark import lua as _lua
        for seed in range(1, 21):
            rc, out, _ = spark("lua", "--sim", str(seed), "auto")
            line = out.splitlines()[0] if out else ""
            m = re.match(r"zone (\d+) stars (\d+) over (\w+)", line)
            if m and int(m.group(2)) >= 1:
                star1.append(seed)
            if m and m.group(3) == "won":
                wins.append((seed, out))
        t.ok(len(star1) == 20, "lua: the pilot takes star 1 on every seed 1..20 (the river is gentle)", "took it on: %s" % star1)
        t.ok(bool(wins), "lua: the pilot wins at least one seed in 1..20", "no win")
        if wins:
            seed, out = wins[0]
            t.ok("Eight stars, the forest crossed." in out and "Ele lembrou" not in out,
                 "lua: a win says so in English, under the banner (seed %d)" % seed, out)
            t.ok("Top runs" in out and out.count("+--") == 0
                 and "Cobra" not in out and "the moon, in Portuguese" not in out,
                 "lua: the win splash is the score and the board -- no box, no credits", out)
            # the palette is the whole forest's prize: a first-night win
            # says what is still to come, and hands over nothing
            t.ok("spark theme canarinho" not in out and "Night 2 awaits" in out,
                 "lua: winning night 1 offers the next night, not the palette", out)
        t.ok(not os.path.exists(mine_dir + "/canarinho.env"),
             "lua: no palette until the last night is won")
        # the last night: the same pilot, the forest at its thickest
        last = ""
        for seed in range(1, 21):
            rc, out, _ = spark("lua", "--night", str(_lua.NIGHTS), "--sim", str(seed), "auto")
            if out.splitlines()[0:1] and " over won " in out.splitlines()[0]:
                last = out
                break
        t.ok(bool(last), "lua: the pilot can still cross on the last night", last[:200])
        if last:
            t.ok("spark theme canarinho" in last and "awaits" not in last,
                 "lua: winning the last night is what hands over the palette", last)
        t.ok(os.path.exists(mine_dir + "/canarinho.env"),
             "lua: the last night writes canarinho.env into your palettes")
        rc, out, err = spark("theme", "canarinho", extra={"SPARK_NO_APPLY": "1"})
        with open(home + "/.config/spark/theme.env") as f:
            theme_env = f.read()
        t.ok(rc == 0 and "THEME_ACCENT=#ffdf00" in theme_env and theme_env.count("THEME_") == 21
             and "THEME_LOGO=bright-green" in theme_env,
             "spark theme canarinho: the prize applies like any palette, its logo colours with it", out + err)
        from spark import cli as _cli
        with open(os.path.join(REPO, "home", ".config", "spark", "banner")) as f:
            banner = f.read()
        painted = _cli.recolour("bright-green bright-green bright-yellow bright-yellow bright-blue bright-blue".split(), banner)
        rows = painted.split("\n")
        t.ok(rows[0].startswith("\\033[1;92m") and rows[1].startswith("\\033[92m") and rows[2].startswith("\\033[93m")
             and rows[4].startswith("\\033[94m") and painted.count("\\033[0m") == banner.count("\\033[0m"),
             "spark ver: the banner takes THEME_LOGO's colours, row by row, the first bold", rows[0][:20])
        import wave as _wave
        import io as _io
        # a death: running and hopping, never firing
        rc, out, _ = spark("lua", "--sim", "1", "dwww")
        t.ok(rc == 0 and "over dead" in out.splitlines()[0] and re.search(r"Zone \d+, ", out)
             and "Score " in out and out.count("+--") == 0 and "Sloth" not in out,
             "lua: a run that never fires dies: the same splash as a win, no box", out)
        rc, out, _ = spark("lua", "--sim", "2", "auto", extra={"SPARK_ASCII": "1", "XDG_STATE_HOME": home + "/.local/state-c"})
        t.ok(rc == 0 and all(ord(c) < 128 for c in out), "lua on the console: every character ASCII, the text folded", out)
        rc, out, _ = spark("lua")
        t.ok(rc == 2 and "a terminal, please" in out and "Karaj" in out and "\x1b" not in out,
             "lua without a tty: one line and the tale's opening, never a frame", out)
        rc, out, _ = spark("lua", "--moon", "2026-09-26")
        t.ok(rc == 0 and out.startswith("Moon: full"), "lua --moon: 2026-09-26 is a full moon", out)
        # the nights: faster, more points; the win opens the next; the board keeps five
        rc, n1, _ = spark("lua", "--sim", "3", "auto", extra={"XDG_STATE_HOME": home + "/.local/state-n"})
        rc, n3, _ = spark("lua", "--night", "3", "--sim", "3", "auto", extra={"XDG_STATE_HOME": home + "/.local/state-n"})
        t1 = re.search(r"ticks (\d+) score (\d+) night 1", n1.splitlines()[0])
        t3 = re.search(r"ticks (\d+) score (\d+) night 3", n3.splitlines()[0])
        t.ok(t1 and t3 and int(t3.group(1)) < int(t1.group(1)) and int(t3.group(2)) > int(t1.group(2)),
             "lua --night 3: the same forest runs faster and pays more than night 1", n1.splitlines()[0] + " | " + n3.splitlines()[0])
        t.ok("Top runs" in n3 and "(night 3)" in n3 and n3.count("+--") == 0,
             "lua: the splash carries the night and the top runs, in no box", n3)
        rc, out, _ = spark("lua", "--scores", extra={"XDG_STATE_HOME": home + "/.local/state-n"})
        t.ok(rc == 0 and out.count("night ") == 2 and "nights won: 3" in out, "lua --scores: the runs so far, and the nights won", out)
        rc, out, _ = spark("help")
        t.ok("lua" not in out.split(), "lua is in no help line")
        # the forest is fair by construction, on thirty seeds, in-process
        # (World only: no state, no config dir, no finish); and the letters
        from spark import lua as _lua
        unfair = {seed: _lua.World(seed).check() for seed in range(1, 31)}
        unfair = {k: v for k, v in unfair.items() if v}
        t.ok(not unfair, "lua: World(seed).check() passes on seeds 1..30", str(unfair)[:400])
        _w = _lua.World(1)
        gate = _w.posts[1]
        shut_before = _w.solid(gate, _lua.LANE, 0)
        _w.stars[0]["taken"] = True
        t.ok(shut_before and not _w.solid(gate, _lua.LANE, 1), "lua: a zone's gate is shut until the star before it is taken")
        _g = _lua.Game(80, seed=4)
        _g.world.bats[:] = [{"ax": _g.hero.x + 8, "x": _g.hero.x + 8, "y": 0.0, "t": 0, "dive": None, "aim": None,
                             "rest": 0, "alive": True}]
        _g.key("v")
        for _ in range(25):
            _g.step()
        t.ok(not _g.world.bats[0]["alive"] and _g.chased == 1 and _g.sweep_cool > 0,
             "lua: v calls the vulture; a bat in the canopy ahead is chased away, then he rests")
        with _wave.open(_io.BytesIO(_lua.synth(_lua.SOUNDS["won"])), "rb") as wv:
            t.ok(wv.getnchannels() == 1 and wv.getsampwidth() == 1 and wv.getframerate() == 22050
                 and abs(wv.getnframes() - sum(ms for _, ms in _lua.SOUNDS["won"]) * 22.05) < 10,
                 "lua: the success fanfare is an 8-bit mono WAV of the notes' length")
        t.ok([len(_lua.Game(80, seed=1, night=n).world.heals) for n in (1, 2, 4, 5, 6)] == [0, 1, 1, 2, 2],
             "lua: potions by night -- none the first night, one on nights 2 to 4, two from the fifth")
        _g = _lua.Game(80, seed=1)
        _g.key("d")
        for _ in range(400):
            _g.step()
            if _g.hero.run == 0 and _g.hero.resume:
                break
        _x = _g.hero.x
        _g.key("w")
        for _ in range(15):
            _g.step()
        t.ok(_g.hero.resume == 0 and _g.hero.run == 1 and _g.hero.x > _x + 3,
             "lua: a log stops the run; the jump over it resumes the run", "x %.1f -> %.1f" % (_x, _g.hero.x))
        art = _lua.letters("GAME OVER")
        t.ok(len(art) == 5 and len(set(len(r) for r in art)) == 1 and len(art[0]) < 60, "lua: GAME OVER is five even rows under 60 columns", str(art))
        # the ending band is a row taller than play's nine (the caption
        # moves under the banner): Band.draw must follow the growth, and
        # close must step below the grown band -- the pty case above
        # leaves with q and never draws an ending, so this is the one
        # place a death or a win meets Band.draw
        _g = _lua.Game(80, seed=1)
        _tl2 = _lua.tale()
        _band = _lua.Band(_io.StringIO())
        _band.open()
        _band.draw(_g.frame(_tl2))
        for _kind in ("dead", "won"):
            _g.over = _kind
            _band.draw(_lua.ending_rows(_g, _tl2, _kind))
        _band.close()
        _end = _band.out.getvalue()
        t.ok("\x1b[10A" in _end and _end.endswith("\n" * 10 + "\x1b[?25h"),
             "lua: the ending band grows to ten rows and Band.draw follows it", repr(_end[-80:]))
        import fcntl
        import pty
        import struct
        import termios
        pid, mfd = pty.fork()
        if pid == 0:                          # the child: spark lua on a real tty
            os.environ.clear()
            os.environ.update(env)
            os.execv(sys.executable, [sys.executable, SPARK, "lua"])
        fcntl.ioctl(mfd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        data, deadline, sent = b"", time.time() + 20, 0
        while time.time() < deadline:
            r, _, _ = select.select([mfd], [], [], 0.2)
            if r:
                try:
                    chunk = os.read(mfd, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                data += chunk
            if sent == 0 and b"HP" in data:
                mark_len = len(data)
                os.write(mfd, b"\x1bOC")                  # Right as a keypad-mode terminal sends it: run
                time.sleep(0.5)
                os.write(mfd, b"\x1b[D")                  # Left as one that ignores keypad mode does: run back
                time.sleep(0.5)
                os.write(mfd, b"s")
                sent = 1
            elif sent == 1 and time.time() > deadline - 17:
                os.write(mfd, b"q")
                sent = 2
        _, status = os.waitpid(pid, 0)
        t.ok(os.WEXITSTATUS(status) == 0 and b"\x1b[?1049h" not in data and b"\x1b[?25l" in data and b"\x1b[?25h" in data,
             "lua on a pty: no alternate screen, the cursor hidden and shown again", repr(data[-300:]))
        t.ok(b"HP" in data and b"@" in data and b"zone 1/8 the river" in data and b"\x1b[9A" in data and b"v the vulture" in data,
             "lua on a pty: the status, the hero, the zone and the hint in a nine-line band redrawn in place", repr(data[:600]))
        t.ok(sent == 2 and len(data) > mark_len + 400, "lua on a pty: the arrow keys run the hero (the forest scrolls)", str(len(data) - mark_len))
        t.ok(b"\x1b[38;5" not in data and b"spark lua -- left in zone" in data, "lua on a pty: eight colours only, and q leaves with one line", repr(data[-200:]))
        t.ok(b"....." in data and b"Ele lembrou" not in data, "lua on a pty: the memory panel is on screen from the start, English only", repr(data[:900]))

        # ---- v1.41: colour and the pulse at the prompt ----------------------
        # sgr()/paint(): three env vars, console-safe SGR only, a tty only
        import pty as _pty
        import spark as _sp
        _saved = {k: os.environ.pop(k) for k in ("SPARK_ACCENT_SGR", "SPARK_MUTED_SGR", "SPARK_WARN_SGR") if k in os.environ}
        try:
            _m, _s = _pty.openpty()
            _tty = os.fdopen(_s, "w")
            t.ok(_sp.sgr("accent") == "" and _sp.paint("*", "accent", _tty) == "*",
                 "sgr/paint: unset means plain, even at a tty")
            os.environ["SPARK_ACCENT_SGR"] = "1;94"
            os.environ["SPARK_WARN_SGR"] = "1;31"
            os.environ["SPARK_MUTED_SGR"] = "38;5;2"
            t.ok(_sp.sgr("accent") == "1;94" and _sp.sgr("warn") == "1;31" and _sp.sgr("muted") == "",
                 "sgr: 1;94 and 1;31 pass, a 38;5;2 value is dropped whole", repr((_sp.sgr("accent"), _sp.sgr("muted"))))
            os.environ["SPARK_MUTED_SGR"] = "x;1"
            t.ok(_sp.sgr("muted") == "" and _sp.paint("...", "muted", _tty) == "...",
                 "sgr: a value that is not digits and semicolons is plain")
            _rl = "\001\033[1;94m\002chat>\001\033[0m\002" if _sp._gnu_readline() else "chat>"
            t.ok(_sp.paint("*", "accent", _tty) == "\033[1;94m*\033[0m"
                 and _sp.paint("chat>", "accent", _tty, readline=True) == _rl,
                 "paint: the escape at a tty; an input() prompt bracketed under GNU readline, plain under libedit",
                 repr((_sp.paint("*", "accent", _tty), _sp.paint("chat>", "accent", _tty, readline=True))))
            with open(os.devnull, "w") as _dn:
                t.ok(_sp.paint("*", "accent", _dn) == "*", "paint: piped is plain even when the var is set")
            # Busy on a pty: the hint-row frames, then one clear; a pipe gets nothing.
            # The slave's bytes reach the master a beat after the write (the
            # tty layer), so read until the master has been quiet for a while.
            import select as _select

            def _drain(fd, quiet=0.3):
                got = b""
                while _select.select([fd], [], [], quiet)[0]:
                    try:
                        chunk = os.read(fd, 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    got += chunk
                return got
            from spark import text as _tx
            _b = _tx.Busy(_tty, above=True)
            _b.start()
            time.sleep(0.8)
            _b.stop()
            _b.stop()                                     # idempotent
            _got = _drain(_m)
            t.ok(_got.startswith(b"\x1b7\x1b[1A\r\x1b[2K\x1b[1;94m*\x1b[0m .")
                 and b"\x1b8" in _got and _got.endswith(b"\x1b7\x1b[1A\r\x1b[2K\x1b8")
                 and b"\x1b[38;5" not in _got and _got.count(b"\x1b7") >= 2,
                 "Busy above: save, up, clear, the accent mark, ASCII dots, restore -- then one clear", repr(_got))
            del os.environ["SPARK_ACCENT_SGR"]
            _b = _tx.Busy(_tty, above=False)
            _b.start()
            time.sleep(0.4)
            _b.stop()
            _got = _drain(_m)
            t.ok(_got.startswith(b"\r\x1b[2K* .") and _got.endswith(b"\r\x1b[2K") and b"\x1b[" not in _got.replace(b"\x1b[2K", b""),
                 "Busy on the row: plain frames without the var, ASCII only, cleared once", repr(_got))
            _tty.close()
            os.close(_m)
            _r, _w = os.pipe()
            _pf = os.fdopen(_w, "w")
            with _tx.Busy(_pf):
                time.sleep(0.4)
            _pf.close()
            t.ok(os.read(_r, 100) == b"", "Busy on a pipe writes nothing at all")
            os.close(_r)
            _quiet = _tx.Busy.hint_row()
            t.ok(not _quiet.live and _quiet.start() is _quiet and _quiet.stop() is None,
                 "Busy.hint_row without SPARK_HINT_ROW=1 is silent")
        finally:
            for k in ("SPARK_ACCENT_SGR", "SPARK_MUTED_SGR", "SPARK_WARN_SGR"):
                os.environ.pop(k, None)
            os.environ.update(_saved)
        # v1.42: a reply's Markdown drawn at a tty, raw when piped; a fence
        # passes through whole
        import io as _io
        from spark import text as _tx2

        class _Tty(_io.StringIO):
            def isatty(self):
                return True

        def _wrap(src, tty, width=200, step=3):
            out = _Tty() if tty else _io.StringIO()
            w = _tx2.Wrap(out, mark=False)
            w.width = width
            for i in range(0, len(src), step):        # streamed in small chunks
                w.feed(src[i:i + step])
            w.close()
            return out.getvalue()
        _md = ("From *Camellia sinensis* leaves.\n- **How it's made**: heated.\n## Varieties\n"
               "Keep *.txt and **/ and _names_ and 2*3*4 alone.\n```\n**not** rendered *here*\n"
               "    indented **stays**\n```\nAfter **bold again**.\n#### four stay\n**unclosed to the end\n")
        _got = _wrap(_md, True)
        t.ok(_got.startswith("From Camellia sinensis leaves.\n- \x1b[1mHow it's made\x1b[22m: heated.\n\x1b[1mVarieties\x1b[0m\n"),
             "Wrap at a tty: *em* plain, **bold** bold, a # heading bold", repr(_got[:120]))
        t.ok("Keep *.txt and **/ and _names_ and 2*3*4 alone." in _got, "Wrap at a tty: marks that flank no word pass through", repr(_got))
        t.ok("```\n**not** rendered *here*\n    indented **stays**\n```\nAfter \x1b[1mbold again\x1b[22m." in _got,
             "Wrap at a tty: a fenced block passes through whole, marks and all", repr(_got))
        t.ok("#### four stay\n\x1b[1munclosed to the end\x1b[0m\n" in _got, "Wrap at a tty: four hashes stay; an unclosed bold ends with the line", repr(_got[-80:]))
        t.ok(_wrap(_md, False) == _md + "\n", "Wrap piped: the model's bytes, not a mark touched")
        _w = _wrap("with **a long bold phrase that must wrap** cleanly at forty\n", True, width=40)
        t.ok(_w == "with \x1b[1ma long bold phrase that must wrap\x1b[22m\ncleanly at forty\n\n", "Wrap at a tty: the width counts glyphs, never escapes (38 visible fit in 40)", repr(_w))
        # every piped path is byte-identical with the vars set: no escape
        # reaches a pipe, piped chat prints no prompt, do's marks stay
        # bare; SPARK_HINT_ROW=1 with no controlling terminal (a new
        # session) still answers, silently
        _col = {"SPARK_ACCENT_SGR": "1;94", "SPARK_MUTED_SGR": "90", "SPARK_WARN_SGR": "1;31"}
        _plain = spark("line", stdin="? files bigger than 1G")[1]
        rc, out, err = spark("line", stdin="? files bigger than 1G", extra=_col)
        t.ok(rc == 0 and out == _plain and "\033[" not in out + err, "line piped with the vars set: byte-identical", repr(out + err))
        rc, out, err = spark("chat", stdin="count\n:q\n", extra=_col)
        t.ok(rc == 0 and "\033[" not in out + err and "\001" not in out and out.startswith("* "),
             "chat piped with the vars set: no prompt, and the mark stays plain", repr(out + err))
        # a reply the cap ended says so on the screen, not on the thread
        rc, out, err = spark("chat", "capped")
        t.ok(rc == 0 and out.startswith("* Half an answer\n! cut at the reply's length -- say: go on\n") and STATE.get("last_max_tokens") == 1200,
             "chat: a finish_reason of length is a warn line, and chat's cap is 1200", repr(out) + " max_tokens=%r" % STATE.get("last_max_tokens"))
        rc, out, err = spark("last")
        t.ok(rc == 0 and "cut at the reply" not in out, "the cut line is not on the thread record", repr(out))
        rc, out, err = spark("what", "does", "capped", "mean")
        t.ok(rc == 0 and STATE.get("last_max_tokens") == 1200, "a bare question has the same 1200 cap", repr(STATE.get("last_max_tokens")))
        rc, out, err = spark("what", "does", "capped", "mean", extra={"SPARK_MAX_TOKENS": "333"})
        t.ok(rc == 0 and STATE.get("last_max_tokens") == 333, "SPARK_MAX_TOKENS sets the cap", repr(STATE.get("last_max_tokens")))
        rc, out, err = spark("what", "does", "capped", "mean", extra={"SPARK_MAX_TOKENS": "7"})
        t.ok(rc == 2 and "50..32000" in out + err, "SPARK_MAX_TOKENS outside 50..32000 is refused", repr(out + err))
        _got = _wrap("use **`vi`** and **`llama.cpp`**, then `main`.\n", True)
        t.ok(_got == "use \x1b[1m`vi`\x1b[22m and \x1b[1m`llama.cpp`\x1b[22m, then `main`.\n\n", "Wrap at a tty: a mark before a backtick opens", repr(_got))
        # a stream that goes quiet mid-reply is one line, never a traceback
        rc, out, err = spark("chat", "stall", extra={"SPARK_TIMEOUT": "1"})
        t.ok(rc != 0 and "Traceback" not in err and "went quiet for 1" in err and "incomplete" in err and out.startswith("* Half an"),
             "chat: a reply that stalls past SPARK_TIMEOUT ends in one line, the half kept", repr(out + err))
        rc, out, err = spark("chat", stdin="stall\n:q\n", extra={"SPARK_TIMEOUT": "1"})
        t.ok(rc == 0 and "Traceback" not in err and err.startswith("spark: http"), "chat REPL: a stalled brain is one line, the chat goes on", repr(err))
        # v1.43: the reveal inside the streaming verbs
        import time as _time
        _p = _Tty()
        _w = _tx2.Wrap(_p, mark=False, cps=100)
        _t0 = _time.monotonic()
        _w.feed("thirty characters go here now.\n")
        _w.close()
        _dt = _time.monotonic() - _t0
        t.ok(0.22 <= _dt <= 1.5 and _p.getvalue() == "thirty characters go here now.\n\n", "Wrap cps=100 at a tty: ~0.3 s for 31 visible characters", "%.2f s" % _dt)
        _q = _io.StringIO()
        _t0 = _time.monotonic()
        _w = _tx2.Wrap(_q, mark=False, cps=5)
        _w.feed("thirty characters go here now.\n")
        _w.close()
        t.ok(_time.monotonic() - _t0 < 0.1 and _q.getvalue() == "thirty characters go here now.\n\n", "Wrap cps piped: no pace at all")
        from spark import cli as _cli
        t.ok(_cli.reveal_flag(["a", "b"]) == (["a", "b"], 0) and _cli.reveal_flag(["--reveal", "40", "x"]) == (["x"], 40)
             and _cli.reveal_flag(["x", "--reveal"]) == (["x"], "auto") and _cli.reveal_flag(["--reveal", "off", "w"]) == (["w"], 0)
             and _cli.reveal_flag(["--reveal", "words", "here"]) == (["words", "here"], "auto"),
             "reveal_flag: no flag = the standing choice (off); N, auto, off after it")
        os.environ["SPARK_REVEAL"] = "auto"
        t.ok(_cli.reveal_flag(["a"]) == (["a"], "auto"), "SPARK_REVEAL=auto is a choice, not the default")
        _saved_rv = os.environ.pop("SPARK_REVEAL", None)
        os.environ["SPARK_REVEAL"] = "off"
        t.ok(_cli.reveal_flag(["a"]) == (["a"], 0), "SPARK_REVEAL=off is the standing choice")
        os.environ["SPARK_REVEAL"] = "25"
        t.ok(_cli.reveal_flag(["a"]) == (["a"], 25), "SPARK_REVEAL=25 is the standing choice")
        os.environ.pop("SPARK_REVEAL", None)
        if _saved_rv is not None:
            os.environ["SPARK_REVEAL"] = _saved_rv
        from spark import reveal as _rv
        t.ok(_rv.auto_cps(None, turns=[]) == 30, "auto_cps: nothing measured -> 30")
        t.ok(_rv.auto_cps(None, turns=[{"tg_tps": 8.0, "tg_n": 100, "chars": 420}]) == 28,
             "auto_cps: 8 tok/s x 4.2 chars/token = 33.6 cps -> 85%% = 28", _rv.auto_cps(None, turns=[{"tg_tps": 8.0, "tg_n": 100, "chars": 420}]))
        t.ok(_rv.auto_cps(None, turns=[{"tg_tps": 60.0, "tg_n": 50, "chars": 200}]) == 40, "auto_cps: a fast model is capped at a reader's 40")
        t.ok(_rv.auto_cps(None, turns=[{"tg_tps": 2.0, "tg_n": 10, "chars": 40}]) == 6, "auto_cps: a slow CPU model paces at 6, still smooth")
        t.ok(_rv.auto_cps(None, turns=[{"tg_tps": 10.0, "tg_n": 0, "chars": 0}, {"tg_tps": "x"}]) == 35, "auto_cps: no length recorded -> 4.2 chars a token; junk skipped")
        rc, out, err = spark("chat", "count")
        _tf = sorted(glob.glob(home + "/.local/state/spark/turns/*.jsonl"))
        _lt = json.loads([l for l in open(_tf[-1], encoding="utf-8").read().splitlines() if l.strip()][-1]) if _tf else {}
        t.ok(isinstance(_lt.get("chars"), int) and _lt["chars"] > 0, "a turn records chars (a count, never the text)", repr(_lt))
        rc, out, err = spark("chat", "--reveal", "200", "count", extra=_col)
        rc2, out2, err2 = spark("chat", "count", extra=_col)
        t.ok(rc == 0 and rc2 == 0 and out.startswith("* ") and "\033[" not in out + err and len(out.splitlines()) == len(out2.splitlines()),
             "chat --reveal piped: the same shape as chat without it, no pace, no escape", repr(out))
        rc, out, err = spark("chat", "--reveal", "999", "count")
        t.ok(rc != 0 and "5..200" in out + err, "chat --reveal 999: refused, the range named", repr(out + err))
        rc, out, err = spark("chat", stdin="/reveal 50\n/reveal x\n/reveal off\n/reveal\n/reveal auto\n:q\n")
        t.ok(rc == 0 and "at 50 characters a second" in out and "/reveal takes a number" in out and "as they are made" in out
             and "the model writes" in out and "characters a second" in out and "never waits on it (auto = " in out and "now: off" in out
             and "at the measured threshold" in out,
             "/reveal 50, x, off, bare (the benchmark), auto inside chat", repr(out))
        rc, out, err = spark("stats")
        t.ok(rc == 0 and "  pace        the model writes" in out and "never waits on it" in out, "spark stats: the pace lines (what the model writes, the threshold)", repr(out))
        # spark bench --line (v1.52): the real spark line path, timed as
        # the widget sees it; the stub's timings read 40 prompt tokens, a
        # warm slot. No turn record (history off): the slot is unknown.
        rc, out, err = spark("bench", "--line", "2", extra={"SPARK_HISTORY": "off"})
        t.ok(rc == 0 and "slots not recorded" in out and re.search(r"^   1  how much disk does this use .* -  -$", out, re.M),
             "bench --line with history off: the times, no slot", repr(out + err))
        n0 = len(STATE.get("bodies", []))
        _tb = sorted(os.listdir(tdir())) if tdir() else []
        rc, out, err = spark("bench", "--line", "3")
        _turns = [json.loads(ln) for f in sorted(_glob.glob(home + "/.local/state/spark/turns/*.jsonl"))
                  for ln in open(f) if ln.strip()]
        t.ok((sorted(os.listdir(tdir())) if tdir() else []) == _tb
             and [x.get("bench") for x in _turns[-3:]] == [1, 1, 1],
             "bench --line: the questions leave no thread; their turns are marked bench", repr(_turns[-3:])[:300])
        table = [ln for ln in out.splitlines() if not ln.startswith("  saved in ")]
        t.ok(rc == 0 and out.startswith("spark bench --line") and len(re.findall(r"^\s+\d  .* warm$", out, re.M)) == 3
             and re.search(r"^      median\s+\d+\.\d\d s\s+\d+\.\d\d s\s+40\s+12$", out, re.M)
             and "the line pace: command ready " in out and "3 warm of 3" in out
             and all(len(ln) <= 80 for ln in table),
             "bench --line 3: a row a question, the medians, 3 warm of 3, 80 columns", repr(out + err))
        asked = [m["content"] for b in STATE.get("bodies", [])[n0:] for m in b["messages"] if m.get("role") == "user"]
        t.ok(any("how much disk does this use" in a for a in asked) and any("which ports are listening" in a for a in asked),
             "bench --line: the questions ride spark line to the model", repr(asked[-3:]))
        last = json.loads([ln for ln in open(home + "/.local/state/spark/bench.jsonl") if ln.strip()][-1])
        t.ok(last.get("size") == "line" and last.get("warm") == 3 and last.get("known") == 3 and last.get("read") == 40
             and ("inside spark line the command was ready" in out) == ("cmd_ms" in last),
             "bench --line: the medians saved as a line record; cmd_ms said only when the turns carry it", repr(last))
        rc, out, err = spark("bench", "--line", "2", "--porcelain")
        lines = out.splitlines()
        t.ok(rc == 0 and len(lines) == 3 and lines[0].split("\t")[5] == "warm" and lines[2].startswith("median\t")
             and lines[2].endswith("\t2/2"), "bench --line --porcelain: a line a question, then the medians", repr(out))
        rc, out, err = spark("bench", "--line", "0")
        rc2, out2, _ = spark("bench", "--line", "x")
        t.ok(rc == 2 and rc2 == 2 and "1 to 20" in out and "1 to 20" in out2, "bench --line 0 | x: refused, the range named", repr(out + out2))
        rc, out, err = spark("stats")
        t.ok(rc == 0 and "  pace        line: command ready " in out and "2 warm of 2 (spark bench --line, " in out,
             "spark stats: the line pace beside the others", repr(out))
        rc, out, err = spark("stats", "--porcelain")
        t.ok(rc == 0 and "line_warm\t2/2" in out and re.search(r"^line_ready_ms\t\d+$", out, re.M)
             and re.search(r"^baseline_tg\t$", out, re.M),
             "spark stats --porcelain: line_*, and a line record is never a llama-bench baseline", repr(out))
        rc, out, err = spark("what", "does", "this", "mean", extra=_col)
        t.ok(rc == 0 and "\033[" not in out + err and out.startswith("* "), "an answer piped with the vars set: no escape", repr(out + err))
        rc, out, err = spark("explain", stdin="ls: cannot access 'x': No such file\n", extra=_col)
        t.ok(rc == 0 and "\033[" not in out + err, "explain piped with the vars set: no escape", repr(out + err))
        rc, out, err = spark("do", "say", "hello", stdin="\n", extra=dict(_col, SPARK_DO_STDIN="1"), cwd=work)
        t.ok(rc == 0 and "\033[" not in out + err and out.splitlines()[0].startswith("* driving with ")
             and "\n* 1  echo STEP-ONE   say hello" in out,
             "spark do piped with the vars set: the driving line and the step marks stay plain", repr(out + err))
        p = subprocess.run([sys.executable, SPARK, "line"], input="? files bigger than 1G", capture_output=True, text=True,
                           env=dict(env, SPARK_HINT_ROW="1", **_col), timeout=30, start_new_session=True)
        t.ok(p.returncode == 0 and p.stdout == _plain and p.stderr == "",
             "spark line with SPARK_HINT_ROW=1 and no terminal: the same two lines, nothing drawn", repr(p.stdout + p.stderr))
        # ---- end of the v1.41 block ------------------------------------------

    # spark reveal: piped it is an exact copy (bytes, no pacing); at a
    # tty it is paced -- 60 chars at 100 cps cannot land in an instant;
    # a wrong CPS and a second word are the usage, signed
    blob = ("abc éçÃo \n" * 40).encode() + b"tail with no newline"
    p = subprocess.run([sys.executable, SPARK, "reveal"], input=blob,
                       capture_output=True, env=env, timeout=30)
    t.ok(p.returncode == 0 and p.stdout == blob, "reveal: piped is an exact copy, byte for byte",
         repr(p.stdout[:80]))
    p = subprocess.run([sys.executable, SPARK, "reveal", "999"], input=b"",
                       capture_output=True, env=env, timeout=30)
    t.ok(p.returncode == 2 and b"5..200" in p.stdout + p.stderr, "reveal: CPS out of range is the usage",
         repr(p.stdout + p.stderr))
    p = subprocess.run([sys.executable, SPARK, "reveal", "30", "x"], input=b"",
                       capture_output=True, env=env, timeout=30)
    t.ok(p.returncode == 2, "reveal: a second word is the usage")
    _m, _s = pty.openpty()
    p = subprocess.Popen([sys.executable, SPARK, "reveal", "100"],
                         stdin=subprocess.PIPE, stdout=_s, stderr=_s, env=env)
    os.close(_s)
    _t0 = time.time()
    p.stdin.write(b"x" * 60)
    p.stdin.close()
    _got = b""
    while len(_got) < 60 and time.time() - _t0 < 15:
        r, _, _ = select.select([_m], [], [], 0.2)
        if r:
            try:
                _got += os.read(_m, 4096)
            except OSError:
                break
    _dt = time.time() - _t0
    os.close(_m)
    p.wait(timeout=10)
    t.ok(_got.count(b"x") == 60 and _dt >= 0.3,
         "reveal: at a tty the characters are paced, not dumped", "%d chars in %.2fs" % (_got.count(b"x"), _dt))

    # completion drift guard: every verb the CLI dispatches (bin/spark's
    # one VERBS table) appears in completion.bash -- a new verb without a
    # completion word goes loud here. The zsh file shares the same
    # tables; the pty completion test proves both live. Verbs excluded
    # from completion on purpose are named in a comment there, which
    # counts: the guard is about forgetting, not about policy.
    comp = open(os.path.join(REPO, "home", ".config", "spark", "completion.bash")).read()
    verbs_src = re.search(r"^VERBS = \{(.*?)\}$", open(SPARK).read(), re.S | re.M).group(1)
    wanted = set(re.findall(r'"([^"]+)":', verbs_src)) | {"help"}
    missing = sorted(w for w in wanted
                     if not re.search(r"(?<![A-Za-z-])%s(?![A-Za-z-])" % re.escape(w), comp))
    t.ok(not missing, "completion.bash names every dispatch verb and cli command",
         "missing: " + " ".join(missing))
    # and every option spark do takes (do.OPTIONS, the help pair aside)
    # is a word after `do` in both files
    from spark import do as _dod
    for cf in ("completion.bash", "completion.zsh"):
        src = open(os.path.join(REPO, "home", ".config", "spark", cf)).read()
        m = re.search(r"^\s*do\)\s+(?:words=\"|comp=\()([^\")]*)", src, re.M)
        have = set(m.group(1).split()) if m else set()
        want = set(_dod.OPTIONS) - {"-h", "--help"}
        t.ok(have == want, "%s completes every spark do option (do.OPTIONS)" % cf,
             "have %s, want %s" % (sorted(have), sorted(want)))

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

    # the guard (v1.48): spark's core is decoupled from any shell layer.
    # Nothing a user installs or runs names one -- not a message, a check
    # row, a help line, a model prompt, a verb, a comment, a fixture. The
    # generic contracts stay and are described as generic: theme.env (the
    # palette any renderer reads), the console palette and font, the
    # three SPARK_*_SGR variables, `spark bar line`. A hit names file:line.
    _guard = re.compile(r"spark-shell|(?i:shell layer)|SITE_SHELL|shell-moved|THEME_BTOP|state/prompt")
    _hits = []
    for _r in ("bin", "lib", "home", "linux", "templates", "themes", "get", "bootstrap.sh", "install.sh", "uninstall"):
        _p = os.path.join(REPO, _r)
        if os.path.isfile(_p):
            _files = [_p]
        elif os.path.isdir(_p):
            _files = [os.path.join(d, f) for d, _, fs in os.walk(_p) for f in fs
                      if "__pycache__" not in d and not f.endswith(".pyc")]
        else:
            continue
        for _f in sorted(_files):
            with open(_f, "rb") as fh:
                _raw = fh.read()
            if b"\0" in _raw:
                continue                    # an image, a font
            for _n, _l in enumerate(_raw.decode("utf-8", "replace").split("\n"), 1):
                if _guard.search(_l):
                    _hits.append("%s:%d" % (os.path.relpath(_f, REPO), _n))
    t.ok(not _hits, "core knows nothing of a shell layer: no core file names one (bin, lib, home, linux, templates, themes, get, bootstrap.sh, install.sh)",
         " ".join(_hits[:12]))

    # widget drift guard: the failure moment's word lists live in two
    # files, one per shell, with no compiler between them. A word added to
    # one and not the other goes loud here, as does a marker or hook that
    # leaves one shell behind.
    wz = open(os.path.join(REPO, "home", ".config", "spark", "widget.zsh")).read()
    wb = open(os.path.join(REPO, "home", ".config", "spark", "widget.bash")).read()

    def wordlist(text, name):
        m = re.search(r"^%s='([^']*)'" % name, text, re.M)
        return sorted(m.group(1).split()) if m else []
    for name in ("_SPARK_DANGER", "_SPARK_QUIET_ONE", "_SPARK_QUIET_RC", "_SPARK_LOOKING"):
        a, b = wordlist(wz, name), wordlist(wb, name)
        t.ok(bool(a) and a == b, "%s is the same list in both widgets" % name,
             "zsh: %s; bash: %s" % (a, b))
    t.ok(wordlist(wz, "_SPARK_DANGER") == sorted(
        "rm dd mkfs shred chown chmod kill killall pkill shutdown reboot halt "
        "poweroff crontab truncate diskutil fdisk parted".split()),
        "the danger list is the agreed one", wordlist(wz, "_SPARK_DANGER"))
    for name, text in (("widget.zsh", wz), ("widget.bash", wb)):
        t.ok("_spark_failed" in text and "_spark_offer_kind" in text and " hook" in text,
             "%s carries the exit-code hook, the predicate and the marker field" % name)
        t.ok("_spark_offer_fix" in text and "SPARK_EXPLAIN_RC=127" in text and "install it" in text,
             "%s carries the two escalations (127 install, the second-Esc-s fix)" % name)

    srv.shutdown()
    print("smoke: %s" % ("all ok" if not t.fail else "%d FAILED" % t.fail))
    return 1 if t.fail else 0


if __name__ == "__main__":
    sys.exit(main())
