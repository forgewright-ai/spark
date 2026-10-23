#!/usr/bin/env python3
# spark tests/forge_smoke.py -- `spark forge` against smoke.py's stub
# llama-server, hermetic: loopback only, a throwaway HOME, stub service
# managers. The forge's upstream resolves through a serve-url file that
# names the stub, so no engine and no model are needed.

import hashlib
import http.client
import io
import ipaddress
import json
import os
import re
import shutil
import signal
import ssl
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from http.server import HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SPARK = os.path.join(REPO, "bin", "spark")
sys.path.insert(0, HERE)
import smoke  # noqa: E402  -- the stub llama-server
import forge_probe  # noqa: E402  -- contract 9's gates, asked from the wire

SEEN = {}                 # what the stub saw last: headers and body
# the foreground forge runs with do.STEP_TIMEOUT set to this (the module
# constant, patched in the forge's own process before bin/spark runs), so
# a hanging /api/do/run step is cut in seconds, not do's 120
STEP_TIMEOUT = 2
# and forge.KEEP_MAX to this, so a user's kept threads reach the cap in
# a handful of requests, not two thousand
KEEP_MAX = 6
FORGE_WRAP = ("import runpy, sys; sys.path.insert(0, sys.argv[1]); from spark import do, forge; "
              "do.STEP_TIMEOUT = %d; forge.KEEP_MAX = %d; sys.argv = sys.argv[2:]; "
              "runpy.run_path(sys.argv[0], run_name='__main__')" % (STEP_TIMEOUT, KEEP_MAX))


class Peek(smoke.Stub):
    """smoke's stub, remembering the request it answered."""

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n)
        SEEN["auth"] = self.headers.get("Authorization", "")
        SEEN["body"] = json.loads(raw or b"{}")
        msgs = SEEN["body"].get("messages") or [{}]
        if SEEN["body"].get("stream") and "dripfeed" in (msgs[-1].get("content") or ""):
            return self.drip()
        if SEEN["body"].get("stream") and "timeoutfeed" in (msgs[-1].get("content") or ""):
            return self.quiet(empty="emptytimeoutfeed" in msgs[-1]["content"])
        if SEEN["body"].get("stream") and "cutfeed" in (msgs[-1].get("content") or ""):
            return self.cut()
        self.rfile = io.BytesIO(raw)
        smoke.Stub.do_POST(self)

    def drip(self):
        """One letter at a time, slowly, so a client can hang up
        mid-answer; the pipe breaking when it does is the point."""
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for _ in range(40):
                self.wfile.write(("data: " + json.dumps({"choices": [{"delta": {"content": "a"}}]}) + "\n\n").encode())
                self.wfile.flush()
                time.sleep(0.05)
            self.wfile.write(b"data: [DONE]\n\n")
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def quiet(self, empty=False):
        """The Forge's 5 s read timeout expires after headers or content."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        if not empty:
            self.wfile.write(b'data: {"choices":[{"delta":{"content":"half an "}}]}\n\n')
        self.wfile.flush()
        time.sleep(6)
        self.close_connection = True

    def cut(self):
        """Half a reply, then the wire dies: the upstream promises more
        bytes than it sends, so the read ends in a BrainError of kind
        cut with the partial already streamed."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", "40000")
        self.end_headers()
        self.wfile.write(b'data: {"choices":[{"delta":{"content":"half an "}}]}\n\n')
        self.wfile.flush()
        self.close_connection = True


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def req(url, method, path, body=None, headers=None, timeout=10):
    """(status, headers, bytes) over one HTTP/1.0-friendly connection; a
    Host header given here replaces the automatic one."""
    u = urllib.parse.urlsplit(url)
    c = http.client.HTTPConnection(u.hostname, u.port, timeout=timeout)
    h = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h.setdefault("Content-Type", "application/json")
    try:
        c.request(method, path, data, h)
        r = c.getresponse()
        return r.status, dict(r.getheaders()), r.read()
    finally:
        c.close()


def sse(raw):
    """[(event, data)] of an SSE body; data parsed as JSON when it is."""
    out = []
    for block in raw.decode("utf-8", errors="replace").split("\n\n"):
        ev, data = "message", []
        for line in block.split("\n"):
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
        if data:
            d = "\n".join(data)
            try:
                d = json.loads(d)
            except ValueError:
                pass
            out.append((ev, d))
    return out


def admin_boundary(ok):
    """The acting admin rows over plain http: a routed peer is 403
    boundary before any body is read; loopback and a peer on one of this
    machine's networks answer, and over TLS the routed peer answers too.
    A fake server, the real _route and the real bearer check."""
    import email.message
    from types import SimpleNamespace
    from unittest.mock import patch
    from spark import forgeserve as fs

    nets = [ipaddress.ip_network("192.0.2.0/24"), ipaddress.ip_network("2001:db8::/64")]
    cases = (("127.0.0.1", True), ("::1", True), ("192.0.2.7", True), ("2001:db8::9", True),
             ("::ffff:192.0.2.7", True), ("203.0.113.9", False), ("2001:db8:1::9", False), ("nonsense", False))
    got = [(ip, fs.peer_is_local(ip, nets)) for ip, _w in cases]
    ok(got == list(cases), "peer_is_local: loopback and the own networks are local, a routed peer is not", got)
    # the three RFC 1918 blocks, built from their numbers: a dotted
    # private address is what the privacy gate refuses in the tree
    blocks = [str(ipaddress.ip_address(n)) for n in ((10 << 24) + 66051, (172 << 24) + (31 << 16) + 7, (192 << 24) + (168 << 16) + 7)]
    ok(all(fs.peer_is_local(ip, []) for ip in blocks) and fs.peer_is_local("fe80::1", []) and fs.peer_is_local("fd00::9", [])
       and not fs.peer_is_local("203.0.113.9", []) and not fs.peer_is_local("2001:db8::9", []),
       "with no networks read, the private and link-local ranges stand in", blocks)
    linux = ("1: lo    inet 127.0.0.1/8 scope host lo\n2: enp2s0    inet 192.0.2.10/24 brd 192.0.2.255 scope global\n"
             "2: enp2s0    inet6 2001:db8::10/64 scope global\n")
    mac = ("lo0: flags=8049\n\tinet 127.0.0.1 netmask 0xff000000\n\tinet6 fe80::1%lo0 prefixlen 64 scopeid 0x1\n"
           "en0: flags=8863\n\tinet 192.0.2.10 netmask 0xffffff00 broadcast 192.0.2.255\n")
    got = [str(n) for n in fs._parse_networks(linux)]
    ok(got == ["127.0.0.0/8", "192.0.2.0/24", "2001:db8::/64"], "ip -o addr parsed to this machine's networks", got)
    got = [str(n) for n in fs._parse_networks(mac)]
    ok(got == ["127.0.0.0/8", "fe80::/64", "192.0.2.0/24"], "ifconfig parsed to this machine's networks", got)

    token = "fixture-admin-" + "x" * 40
    logged = []

    def ask(ip, scheme, method, path, as_admin=True):
        server = SimpleNamespace(scheme=scheme, hosts={"127.0.0.1:1"}, cfg=SimpleNamespace(name="fixture"),
                                 admin_token=lambda: token, locked_out=lambda ip: False, failed=lambda ip: None,
                                 user_by_bearer=lambda t: None, session_of=lambda sid: None,
                                 local_peer=lambda ip: fs.peer_is_local(ip, nets))
        h = object.__new__(fs.Handler)
        h.server, h.client_address, h.command = server, (ip, 1), method
        h.headers = email.message.Message()
        h.headers["Host"] = "127.0.0.1:1"
        h.headers["X-Spark"] = "1"
        if as_admin:
            h.headers["Authorization"] = "Bearer " + token
        answers = []
        h._error = lambda code, kind, hint, extra=None: answers.append((code, kind))
        h._body = lambda: {}
        for name in ("api_run", "api_do_propose", "api_do_run", "api_check_refresh", "api_soul_write", "api_users_add",
                     "api_users_remove", "api_serve"):
            setattr(h, name, lambda body=None, name=name: answers.append(name))
        with patch.object(fs, "log", lambda line: logged.append(line)):
            h._route(method, path)
        return answers

    for method, pattern in fs.ACTS:
        path = pattern.replace("*", "nobody")      # a `*` is one segment: the boundary reads it as the table does
        a = ask("203.0.113.9", "http", method, path)
        ok(a == [(403, "boundary")], "%s %s over plain http from a routed peer: 403 boundary, the body unread" % (method, path), a)
        for ip, scheme in (("203.0.113.9", "https"), ("192.0.2.7", "http"), ("127.0.0.1", "http"), ("2001:db8::9", "http")):
            a = ask(ip, scheme, method, path)
            ok(len(a) == 1 and isinstance(a[0], str), "%s %s from %s over %s: the route runs" % (method, path, ip, scheme), a)
    a = ask("203.0.113.9", "http", "GET", "/api/serve")
    ok(a == ["api_serve"], "a view (GET /api/serve) is no act: it answers a routed peer over plain http", a)
    a = ask("203.0.113.9", "http", "POST", "/api/run", as_admin=False)
    ok(a == [(401, "auth")], "no bearer from a routed peer: the 401 comes first, nothing about the boundary", a)
    ok(sum("refused: POST /api/run over plain http" in line for line in logged) == 1, "the refusal is one line in the log", logged)


def generation_admission(ok):
    """Synthetic slow engines on all three routes; real peer sockets."""
    from contextlib import ExitStack
    from types import SimpleNamespace
    from unittest.mock import patch
    from spark import do, forge, forgeserve as fs, session, wire

    def until(check):
        end = time.monotonic() + 3
        while not check() and time.monotonic() < end:
            time.sleep(0.005)
        assert check(), 'fixture did not reach its barrier'

    with ExitStack() as stack:
        stack.enter_context(patch.object(fs, 'GENERATION_TIMEOUT', 3))
        stack.enter_context(patch.object(fs, 'QUEUE_WAIT', 0.02))
        stack.enter_context(patch.object(session, 'prune'))
        stack.enter_context(patch.object(forge, 'prune_stores'))
        mint = stack.enter_context(patch.object(forge, 'new_thread', return_value='fixture'))
        stack.enter_context(patch.object(do, 'conclusion_check', return_value=[]))
        server = SimpleNamespace(
            generations=fs.GenerationQueue(), cfg=SimpleNamespace(timeout=1),
            upstream=SimpleNamespace(require=lambda: 'fixture', brain=lambda: None,
                                     resolve=lambda **kw: ('fixture', '', 'ok')),
            role_models=lambda url: {}, _auth_lock=threading.Lock(), _user_keys={}, sessions={})
        entered, release = threading.Event(), threading.Event()
        calls, failures, threads = [], [], []

        def engine(name):
            calls.append(name)
            if name == 'slow':
                entered.set()
                assert release.wait(3), 'fixture engine stayed blocked'
            if name == 'fail':
                raise wire.BrainError('timeout', 'fixture timeout')

        def reply(cfg, thread, text, **kw):
            engine(text)
            kw['on_delta']('fixture')
            return 'fixture', '', {}

        def post(cfg, up, body, timeout, stream):
            engine(body['messages'][0]['content'])
            response = io.BytesIO(b'{}')
            response.headers = {}
            return response

        def propose(cfg, thread, text, *args, **kw):
            engine(text)
            return {'danger': False, 'kind': 'done'}, {}, SimpleNamespace(record=lambda **kw: None)

        stack.enter_context(patch.object(forge, 'reply', side_effect=reply))
        stack.enter_context(patch.object(wire, '_post', side_effect=post))
        stack.enter_context(patch.object(do, 'propose', side_effect=propose))

        def request(route, name, owner='admin', stream=False, broken=False):
            sock, peer = socket.socketpair()
            stack.callback(sock.close)
            stack.callback(peer.close)
            h = object.__new__(fs.Handler)
            h.connection, h.server = sock, server
            h.role, h.user = ('admin', '') if owner == 'admin' else ('user', owner)
            h.events, h.answers, h.started, h._status = [], [], [], 0
            h._sse = lambda: h.started.append('sse')
            h._emit = lambda event, data: h.events.append((event, data))
            if broken:
                h._emit = lambda *args: (_ for _ in ()).throw(BrokenPipeError())
            h._error = lambda code, kind, hint, headers=None: h.answers.append((code, kind, headers))
            h._json = lambda code, data: h.answers.append((code, data))
            h._start = lambda *args: h.started.append(args)
            h.wfile = io.BytesIO()
            h._thread_of = lambda body: (None, True)
            h._ustore = h._mstore = lambda: None
            h._ip = lambda: '192.0.2.1'
            h._v1_role = lambda model: model
            h._do_cwd = lambda cwd: '/tmp'
            body = {'text': name, 'messages': [{'role': 'user', 'content': name}],
                    'identity': False, 'stream': stream}

            def run():
                try:
                    getattr(h, route)(body)
                except BrokenPipeError:
                    if not broken:
                        failures.append('unexpected broken pipe')
                except Exception as e:
                    failures.append(repr(e))
            t = threading.Thread(target=run)
            threads.append(t)
            t.start()
            return h, peer, t

        def queued(n):
            until(lambda: len(server.generations.waiting) == n)

        # One slow generation, then mixed browser/API callers in admission order.
        a, _, ta = request('api_chat', 'slow')
        assert entered.wait(2)
        b, _, tb = request('api_do_propose', 'second')
        queued(1)
        busy, _, tx = request('v1_chat', 'over-user')
        tx.join(2)
        ok(busy.answers == [(429, 'busy', {'Retry-After': '1'})],
           'browser and API share the two-outstanding account limit', busy.answers)
        c, _, tc = request('api_chat', 'third', 'peer-a')
        queued(2)
        d, _, td = request('v1_chat', 'fourth', 'peer-b', stream=True)
        queued(3)
        e, _, te = request('v1_chat', 'fifth', 'peer-c')
        queued(4)
        full, _, tf = request('api_chat', 'over-global', 'peer-d')
        tf.join(2)
        ok(full.answers == [(429, 'busy', {'Retry-After': '1'})] and not full.started,
           'four waiting requests fill the queue; excess chat gets HTTP 429 before SSE')
        release.set()
        for t in (ta, tb, tc, td, te):
            t.join(2)
        ok(calls == ['slow', 'second', 'third', 'fourth', 'fifth'],
           'chat, proposals, JSON and streaming API requests run serially in FIFO order', calls)

        mint.reset_mock()
        stack.enter_context(patch.object(fs, 'GENERATION_TIMEOUT', 0.6))
        # Every waiting route expires, recovers its account slot and never calls the engine.
        for route in ('api_chat', 'v1_chat', 'api_do_propose'):
            entered.clear()
            release.clear()
            _, _, slow = request('api_chat', 'slow', 'holder')
            assert entered.wait(2)
            timed, _, waiter = request(route, 'expired')
            waiter.join(2)
            ok(not waiter.is_alive() and 'expired' not in calls and
               ((timed.events[-1][0] == 'error' and timed.events[-1][1]['kind'] == 'timeout')
                if route == 'api_chat' else timed.answers == [(504, 'timeout', {'Retry-After': '1'})]),
               route + ': queue deadline ends waiting without inference')
            queued(0)
            # A disconnected queued request is removed while the holder is still running.
            gone, peer, waiter = request(route, 'disconnected')
            queued(1)
            peer.close()
            waiter.join(0.4)
            ok(not waiter.is_alive() and gone._status == 499 and 'disconnected' not in calls,
               route + ': disconnect promptly frees the waiting slot')
            ok(not mint.called, route + ': a refused proposal creates no thread')
            release.set()
            slow.join(2)

        # Deterministic handoff boundaries: a free slot cannot revive stale work.
        h = object.__new__(fs.Handler)
        sock, peer = socket.socketpair()
        stack.callback(sock.close)
        h.connection = sock
        peer.close()
        for reason in ('disconnect', 'deadline'):
            q = fs.GenerationQueue()
            ticket = q.reserve(('user', 'peer'))
            try:
                with patch.object(fs.time, 'monotonic', return_value=ticket[2] + 1):
                    q.wait(ticket, h._connected if reason == 'disconnect' else lambda: True)
            except (ConnectionAbortedError, TimeoutError) as exc:
                ok(type(exc) is (ConnectionAbortedError if reason == 'disconnect' else TimeoutError),
                   reason + ': stale request cannot claim an already free model')
            else:
                ok(False, reason + ': stale request started')
            finally:
                q.release(ticket)
            ok(q.active is None and not q.waiting, reason + ': cancelled ticket is released')

        # Engine errors and a failed SSE write both release serialization.
        for route in ('api_chat', 'v1_chat', 'api_do_propose'):
            _, _, t = request(route, 'fail')
            t.join(2)
            _, _, t = request(route, 'recovered')
            t.join(2)
            ok(calls[-2:] == ['fail', 'recovered'], route + ': engine timeout releases the slot')
        _, _, t = request('api_chat', 'write-failed', broken=True)
        t.join(2)
        _, _, t = request('api_do_propose', 'after-write')
        t.join(2)
        ok(calls[-2:] == ['write-failed', 'after-write'] and not server.generations.waiting
           and server.generations.active is None, 'failed output releases the slot')
        ok(not failures and not any(t.is_alive() for t in threads),
           'generation fixtures leave no request threads or unexpected errors', failures)


def reply_interruptions(ok):
    """Real SSE parsing, sessions and sealed history; no model or clock waits."""
    from contextlib import ExitStack
    from unittest.mock import patch
    from spark import cli, config, forge, session, wire

    class Response:
        def __init__(self, pieces, failure=None):
            self.pieces, self.failure = pieces, failure

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def __iter__(self):
            for piece in self.pieces:
                yield ('data: ' + json.dumps({'choices': [{'delta': {'content': piece}}]}) + '\n').encode()
            if self.failure:
                raise self.failure
            yield b'data: [DONE]\n'

    with tempfile.TemporaryDirectory(prefix='spark-reply-') as tmp, ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, {"SPARK_HISTORY": "7"}))
        cfg = config.load()
        stack.enter_context(patch.object(forge, 'state_dir', return_value=tmp))
        stack.enter_context(patch.object(session.Session, '_system', return_value='fixture'))
        stack.enter_context(patch.object(session.Session, 'record'))
        store = forge.Store(os.path.join(tmp, 'threads'), b'x' * 32)
        brain = lambda fresh: ('http://127.0.0.1:1', 'fixture', False)
        for kind, failure in [('timeout', socket.timeout('timed out')),
                              ('cut', ConnectionResetError('reset')),
                              ('interrupt', KeyboardInterrupt())]:
            for pieces in ([], ['half ', 'an answer']):
                for history in (0, 7):
                    os.environ["SPARK_HISTORY"] = str(history)
                    visible, said = [], []
                    with patch.object(wire, '_send', return_value=Response(pieces, failure)) as send:
                        try:
                            forge.reply(cfg, None, 'question', store=store, brain=brain,
                                        on_delta=visible.append, said=said)
                        except (wire.BrainError, KeyboardInterrupt) as exc:
                            tid = getattr(exc, 'thread', None)
                            ok(not isinstance(exc, wire.BrainError) or exc.kind == kind,
                               'stream failure keeps its kind: ' + kind)
                        else:
                            ok(False, 'stream failure must be raised: ' + kind)
                            continue
                    rows = store.load(tid) if tid else []
                    partial = ''.join(pieces)
                    expected = 2 if partial else (1 if kind != 'timeout' else 0)
                    ok(send.call_count == 1 and visible == pieces,
                       'interrupted stream is delivered once, never retried')
                    ok(len(rows) == (expected if history else 0)
                       and (not history or not partial or
                            (rows[-1]['text'] == partial and rows[-1].get('partial') is True)),
                       'partial history exactly once: %s, content=%s, history=%s' % (kind, bool(pieces), history), rows)
                    ok(history or (tid is None), 'history off creates no thread')
                    ok(said == [], 'interruption leaves the existing transient-memory behavior unchanged')
                    if partial and history:
                        with patch.object(wire, '_send', return_value=Response(['continued'])) as send:
                            resumed, answer, _ = forge.reply(cfg, tid, 'go on', store=store, brain=brain)
                        messages = json.loads(send.call_args[0][2])['messages']
                        ok(resumed == tid and answer == 'continued' and len(store.load(tid)) == 4
                           and messages[-3:] == [{'role': 'user', 'content': 'question'},
                                                 {'role': 'assistant', 'content': partial},
                                                 {'role': 'user', 'content': 'go on'}],
                           'follow-up uses the saved partial on the same thread')

        os.environ["SPARK_HISTORY"] = "7"
        for second in (Response(['retried']), wire.BrainError('down', 'still down'),
                       Response(['retry partial'], socket.timeout('timed out'))):
            with patch.object(wire, '_send', side_effect=[wire.BrainError('down', 'down'), second]) as send:
                resolves = []
                def resolve(fresh):
                    resolves.append(fresh)
                    return brain(fresh)
                before = len(store.list_threads(n=100))
                try:
                    tid, answer, _ = forge.reply(cfg, None, 'retry', store=store, brain=resolve)
                except wire.BrainError as exc:
                    if exc.kind == 'timeout':
                        rows = store.load(getattr(exc, 'thread', None))
                        ok(len(rows) == 2 and rows[-1]['text'] == 'retry partial'
                           and rows[-1].get('partial') is True, 'timeout on retry saves its partial once')
                    else:
                        ok(len(store.list_threads(n=100)) == before, 'failed retry persists no turn')
                else:
                    ok(answer == 'retried' and len(store.load(tid)) == 2,
                       'successful retry persists one pair')
                ok(send.call_count == 2 and resolves == [False, True], 'down before content retries once')

        # Kept threads still save turns when ordinary history is disabled.
        tid, _ = store.keep()
        os.environ["SPARK_HISTORY"] = "0"
        for turn in range(2):
            with patch.object(wire, '_send', return_value=Response(['kept'], socket.timeout('timed out'))):
                try:
                    forge.reply(cfg, tid, 'keep going', store=store, brain=brain)
                except wire.BrainError as exc:
                    ok(exc.thread == tid and len(store.load(tid)) == 2 * (turn + 1),
                       'repeated interrupted turns keep the same kept thread without duplicating earlier turns')
        os.environ["SPARK_HISTORY"] = "7"

        # A late down error must not replay words already delivered to the caller.
        def late_down(*args, **kwargs):
            args[3]('once')
            raise wire.BrainError('down', 'late failure')
        with patch.object(wire, 'chat_stream', side_effect=late_down) as stream:
            try:
                forge.reply(cfg, None, 'late', store=store, brain=brain)
            except wire.BrainError as exc:
                tid = getattr(exc, 'thread', None)
            ok(stream.call_count == 1 and tid and store.load(tid)[-1]['text'] == 'once',
               'content prevents a down retry and lands once')

        # The terminal loop must adopt the exception's thread just like the page.
        failure = wire.BrainError('timeout', 'fixture timeout')
        failure.thread = '2026-01-01-000000'
        with patch.object(config, 'load', return_value=cfg), \
                patch.object(forge, 'last_thread', return_value=None), \
                patch.object(forge, '_voice_setup'), patch.object(forge, '_spoken', return_value=None), \
                patch.object(forge, '_face_rest'), patch.object(forge, '_refuse'), \
                patch.object(sys, 'stdin', io.StringIO('question\ngo on\n')), \
                patch.object(sys, 'stdout', io.StringIO()), \
                patch.object(cli, 'stream_turn', side_effect=[failure, failure.thread]) as stream:
            forge.cmd_chat([])
        ok(stream.call_args_list[1].kwargs['thread'] == failure.thread,
           'terminal follow-up adopts the partial thread after a timeout')


def _gone(pid):
    """True when pid no longer runs: missing, or a zombie nobody reaped yet
    (/proc on Linux; macOS has none, and its launchd reaps an orphan)."""
    if os.path.isdir("/proc/self"):
        try:
            with open("/proc/%d/stat" % pid) as f:
                return f.read().rsplit(")", 1)[1].split()[0] == "Z"
        except FileNotFoundError:
            return True
        except OSError:
            pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except OSError:
        pass
    return False


def verb_runner(ok):
    """/api/run's runner on synthetic processes, short caps: the verb's
    lines, its deadline, a hang-up, and a service it hands off."""
    from spark import forgeserve

    def gone_soon(pid, seconds=3):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if _gone(pid):
                return True
            time.sleep(0.05)
        return False

    with tempfile.TemporaryDirectory(prefix="spark-run-") as tmp:
        pidf = os.path.join(tmp, "pid")

        def sh(script):
            return ["sh", "-c", script, "sh", pidf]

        def pid():
            with open(pidf) as f:
                return int(f.read().split()[0])

        lines = []
        rc = forgeserve.run_verb(sh("echo one; printf two"), None, lines.append, cap=5)
        ok(rc == 0 and lines == ["one", "two"], "/api/run's runner: every line, a partial last one too, rc 0",
           (rc, lines))

        lines, t0 = [], time.monotonic()
        rc = forgeserve.run_verb(sh("echo $$ > \"$1\"; echo start; sleep 30"), None, lines.append, cap=1)
        took = time.monotonic() - t0
        ok(rc == 124 and lines == ["start"] and took < 4 and gone_soon(pid()),
           "/api/run's runner: a quiet verb past its cap is rc 124, killed and reaped", (rc, lines, took))

        lines, t0 = [], time.monotonic()
        rc = forgeserve.run_verb(sh("sleep 30 & echo $! > \"$1\"; echo left"), None, lines.append, cap=20)
        took = time.monotonic() - t0
        ok(rc == 0 and lines == ["left"] and took < 4 and gone_soon(pid()),
           "/api/run's runner: a verb that exits leaves no child holding its pipe", (rc, lines, took))

        def hang_up(s):
            raise BrokenPipeError("the page left")
        t0 = time.monotonic()
        try:
            forgeserve.run_verb(sh("sleep 30 & echo $! > \"$1\"; echo x; wait"), None, hang_up, cap=20)
            left = False
        except BrokenPipeError:
            left = True
        took = time.monotonic() - t0
        ok(left and took < 4 and gone_soon(pid()),
           "/api/run's runner: a hang-up kills what the verb started", (left, took))

        handoff = ("import subprocess, sys; p = subprocess.Popen(['sleep', '30'], start_new_session=True, "
                   "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
                   "open(sys.argv[1], 'w').write(str(p.pid))")
        rc = forgeserve.run_verb([sys.executable, "-c", handoff, pidf], None, [].append, cap=5)
        served = pid()
        alive = not _gone(served)
        try:
            os.kill(served, signal.SIGKILL)
        except OSError:
            pass
        ok(rc == 0 and alive, "/api/run's runner: a service started in a session of its own keeps running", rc)

        lines = []
        rc = forgeserve.run_verb(["sh", "-c", "echo next"], None, lines.append, cap=5)
        ok(rc == 0 and lines == ["next"], "/api/run's runner: the next verb runs as usual", (rc, lines))
        rc = forgeserve.run_verb([os.path.join(tmp, "nothing")], None, lines.append, cap=5)
        ok(rc == 127 and lines[-1].startswith("! cannot run"), "/api/run's runner: a verb that cannot start is rc 127",
           (rc, lines))
def free_pair():
    """Two free ports side by side: the page's and the root listener's."""
    while True:
        p = free_port()
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", p + 1))
            return p
        except OSError:
            continue
        finally:
            s.close()


def tls_cases(ok, spark, env, home, state, exe):
    """v1.91, the page over TLS, by hand in this scratch home: the verb's
    refusals, a pair served (the listener, its headers and gates over
    https, the https row, the login's lines), a pair that does not load,
    own mode with the root's listener, a client in a second home that is
    refused, pins the root, pins the leaf, trusts a CA file and forgets,
    and https off. The pair comes from the openssl binary (smoke.mint_pair)."""
    d = os.path.join(home, "pair")
    smoke.mint_pair(exe, d, {"leaf": (["fixture.local", "fixture"], ["127.0.0.1"])}, ["fixture.local", "fixture"])
    cert, key, root = (os.path.join(d, f) for f in ("leaf.crt", "leaf.key", "root.crt"))
    port = free_pair()
    url = "https://127.0.0.1:%d" % port
    tenv = {"SPARK_FORGE_PORT": str(port), "SPARK_FORGE_CERT": cert, "SPARK_FORGE_KEY": key}
    ctx = ssl.create_default_context(cafile=root)
    sys.path.insert(0, os.path.join(REPO, "lib"))
    from spark import tls, wire

    def hreq(method, path, body=None, headers=None, timeout=10, p=None, cafile=None):
        c = http.client.HTTPSConnection("127.0.0.1", p or port, timeout=timeout,
                                        context=ssl.create_default_context(cafile=cafile) if cafile else ctx)
        h = dict(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h.setdefault("Content-Type", "application/json")
        try:
            c.request(method, path, data, h)
            r = c.getresponse()
            return r.status, dict(r.getheaders()), r.read()
        finally:
            c.close()

    def start(extra):
        p = subprocess.Popen([sys.executable, SPARK, "forge", "--foreground"], env=dict(env, **extra),
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        deadline = time.time() + 20
        st = 0
        while time.time() < deadline and st != 200:
            try:
                st = hreq("GET", "/api/health", p=int(extra["SPARK_FORGE_PORT"]), cafile=extra.get("CAFILE"))[0]
            except (OSError, http.client.HTTPException):
                st = 0
            if st != 200:
                time.sleep(0.3)
        return p, st

    def stop(p):
        p.send_signal(signal.SIGTERM)
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()

    def row(extra=None, name="https"):
        rc, out, _ = spark("check", "--porcelain", extra=extra)
        for line in out.splitlines():
            f = line.split("\t")
            if len(f) >= 4 and f[2] == name:
                return f[1], f[3], (f[4] if len(f) > 4 else "")
        return ("missing", out[-300:], "")

    try:
        # the verb: plain first, then its refusals, then the pair
        rc, out, _ = spark("serve", "https")
        ok(rc == 0 and "plain http" in out and "spark serve https own" in out, "spark serve https, plain: says so and names both ways", out)
        rc, out, _ = spark("serve", "https", cert, os.path.join(d, "root.key"))
        ok(rc == 2 and "does not load" in out, "a key that is not the certificate's is refused, nothing written", out)
        rc, out, _ = spark("serve", "https", cert, key, "--name", "other.example")
        ok(rc == 2 and "does not name other.example" in out and "fixture.local" in out, "a name the certificate lacks is refused, its names said", out)
        os.chmod(key, 0o644)
        rc, out, _ = spark("serve", "https", cert, key)
        ok(rc == 2 and "readable by others" in out, "a key others can read is refused", out)
        os.chmod(key, 0o600)
        ok("SPARK_FORGE_CERT" not in open(home + "/.config/spark/spark.env").read(), "no refusal wrote a key")
        # half a pair, before spark.env holds one: refused before anything binds
        rc, out, err = spark("forge", "--foreground", extra={"SPARK_FORGE_PORT": str(port), "SPARK_FORGE_CERT": cert}, timeout=20)
        ok(rc == 2 and "go together" in out + err, "one key without the other: refused, exit 2", out + err)
        rc, out, _ = spark("serve", "https", cert, key)
        ok(rc == 0 and "your pair" in out and "fixture.local, fixture, 127.0.0.1" in out and "sha256:" in out,
           "spark serve https CERT KEY: the pair written, the show with names and fingerprint", out)
        ok("SPARK_FORGE_CERT=%s" % cert in open(home + "/.config/spark/spark.env").read(), "spark.env names the pair")
        rc, out, _ = spark("serve", "https", cert, key, "--name", "fixture.local")
        ok(rc == 0 and "https://fixture.local:%d/login" % port in spark("serve", "https", extra=tenv)[1],
           "--name HOST: the page's link says the name", out)
        rc, out, _ = spark("serve", "https", cert, key)      # the address again for the probes below
        # the page over TLS
        p, st = start(dict(tenv, CAFILE=root))
        try:
            ok(st == 200, "--foreground answers /api/health over TLS")
            if st != 200:
                print(p.communicate()[0][-1500:])
            ok(open(state + "/forge-url").read().strip() == url, "forge-url carries https://")
            try:
                req("http://127.0.0.1:%d" % port, "GET", "/api/health", timeout=5)
                plain = "answered"
            except (OSError, http.client.HTTPException):
                plain = "refused"
            ok(plain == "refused", "a plain-text client gets no page from the TLS port")
            st, hd, _ = hreq("GET", "/")
            ok(st == 200 and "Strict-Transport-Security" not in hd, "the page by address: 200, no HSTS", (st, hd.get("Strict-Transport-Security")))
            st, hd, _ = hreq("GET", "/", headers={"Host": "fixture.local:%d" % port})
            ok(st == 200 and hd.get("Strict-Transport-Security") == "max-age=604800",
               "the page by a name the certificate carries: answered (the name is the page's), HSTS one week", (st, hd.get("Strict-Transport-Security")))
            st, _, _ = hreq("GET", "/api/health", headers={"Host": "evil.example"})
            ok(st == 400, "a Host that is not the page's is 400 over TLS too", st)
            admin = open(state + "/forge-token").read().strip()
            st, hd, _ = hreq("POST", "/api/login", {"token": admin}, {"X-Spark": "1", "Origin": url})
            ok(st == 200 and "; Secure" in hd.get("Set-Cookie", ""), "login over TLS with its own origin: 200, a Secure cookie", (st, hd.get("Set-Cookie", "")[-40:]))
            st, _, _ = hreq("POST", "/api/login", {"token": admin}, {"X-Spark": "1", "Origin": "http://127.0.0.1:%d" % port})
            ok(st == 403, "an http Origin on the https page is refused", st)
            os.environ["SPARK_CA_FILE"] = root
            tls.HANDLER.refresh()
            try:
                gates = wire.probe_gates(url)
            finally:
                del os.environ["SPARK_CA_FILE"]
                tls.HANDLER.refresh()
            ok(len(gates) == len(wire.GATES) and all(g[1] for g in gates), "the eight gates hold over TLS", [g for g in gates if not g[1]])
            status, value, remedy = row(tenv)
            ok(status == "ok" and "fixture.local" in value and "days left" in value, "the https row: ok, the names, the days", (status, value, remedy))
            status, value, remedy = row(tenv, "hardening")
            ok(status == "ok" and "8 of 8" in value, "the hardening row probes the page over TLS through the machine's own trust", (status, value, remedy))
            rc, out, _ = spark("serve", "--login", "--show-token", "--no-qr", extra=tenv)
            ok(rc == 0 and out.splitlines()[0] == url + "/login" and "cert   fixture.local" in out and "sha256 sha256:" in out,
               "spark serve --login: the https link, the certificate's names, its fingerprint", out[:300])
            ok("there:  spark client %s" % url in out, "the join steps say the https URL", out[-200:])
        finally:
            stop(p)
        # a pair that does not load: refused before anything binds
        rc, out, err = spark("forge", "--foreground", extra=dict(tenv, SPARK_FORGE_KEY=root), timeout=20)
        ok(rc == 78 and "does not load" in out + err, "--foreground with a pair that does not load: 78, the reason", out + err)
        # own mode: a root of this machine's own and the root's listener
        port2 = free_pair()
        url2 = "https://127.0.0.1:%d" % port2
        oenv = {"SPARK_FORGE_PORT": str(port2)}
        rc, out, _ = spark("serve", "https", "own", extra=oenv)
        own = os.path.join(state, "https")
        ok(rc == 0 and "a root of this machine's own" in out and "the page's certificate" in out and "each device installs the root once" in out,
           "spark serve https own: the root and the certificate minted, the show", out[:400])
        ok(all(os.stat(os.path.join(own, f)).st_mode & 0o777 == 0o600 for f in ("root.key", "leaf.key")), "the minted keys are 0600")
        rc, out, _ = spark("serve", "https", "own", extra=oenv)
        ok(rc == 0 and "a root of" not in out, "own again: nothing minted twice", out[:300])
        rc, out, _ = spark("serve", "https", "own", "--name", "elsewhere.example", extra=oenv)
        ok(rc == 2 and "does not cover elsewhere.example" in out, "a name the root does not cover is refused", out)
        p, st = start(dict(oenv, CAFILE=os.path.join(own, "root.crt")))
        try:
            ok(st == 200, "the page answers over TLS with the own pair")
            if st != 200:
                print(p.communicate()[0][-1500:])
            st, hd, body = req("http://127.0.0.1:%d" % (port2 + 1), "GET", "/ca")
            ok(st == 200 and hd.get("Content-Type") == "application/x-x509-ca-cert" and body == tls.read_pem(os.path.join(own, "root.crt")),
               "GET /ca on the root's listener: the root in DER, the type phones install from", (st, hd.get("Content-Type"), len(body)))
            st, _, body = req("http://127.0.0.1:%d" % (port2 + 1), "GET", "/")
            ok(st == 200 and b"install the certificate at http://127.0.0.1:%d/ca" % (port2 + 1) in body and url2.encode() in body,
               "GET / there says what to do", body[:160])
            sts = [req("http://127.0.0.1:%d" % (port2 + 1), m, pth)[0] for m, pth in (("GET", "/api/health"), ("HEAD", "/"), ("POST", "/ca"), ("GET", "/login"))]
            ok(sts == [404, 404, 404, 404], "every other route and method there is 404", sts)
            rc, out, _ = spark("serve", "--login", "--show-token", "--no-qr", extra=oenv)
            ok("root   sha256:" in out and "each device installs it once" in out, "spark serve --login in own mode names the root", out[:400])
            rc, out, _ = spark("serve", "https", extra=oenv)
            ok("a root and a certificate of this machine's own" in out and "root     sha256:" in out and "each device installs the root once" in out,
               "spark serve https in own mode: the root, who installs it", out[:400])
            status, value, _ = row(oenv)
            ok(status == "ok" and "the root on each device" in value, "the https row in own mode", (status, value))
            root_fp = tls.read_cert(os.path.join(own, "root.crt"))["sha256"]
            leaf_fp = tls.read_cert(os.path.join(own, "leaf.crt"))["sha256"]
            # a client in a second home
            chome = tempfile.mkdtemp(prefix="spark-tls-client-")
            for sub in (".config/spark", ".local/state/spark", ".local/share/spark"):
                os.makedirs(os.path.join(chome, sub))
            os.chmod(os.path.join(chome, ".local/state/spark"), 0o700)
            cenv = {"HOME": chome, "XDG_CONFIG_HOME": chome + "/.config", "XDG_STATE_HOME": chome + "/.local/state",
                    "XDG_DATA_HOME": chome + "/.local/share"}
            trust = os.path.join(chome, ".config", "spark", "trust")
            rc, out, _ = spark("client", url2, extra=cenv)
            ok(rc == 2 and "is not trusted here" in out and leaf_fp in out and "--pin FINGERPRINT" in out and "--ca FILE" in out,
               "a client of a page it does not trust is refused with the fingerprint and both remedies", out)
            ok(not os.path.exists(os.path.join(chome, ".config", "spark", "site.env")), "and nothing was set")
            rc, out, _ = spark("client", url2, "--pin", "sha256:" + ":".join(["00"] * 32), extra=cenv)
            ok(rc == 2 and "matches neither" in out and not os.path.exists(trust), "a fingerprint that matches nothing: refused, nothing saved", out)
            rc, out, _ = spark("client", url2, "--pin", root_fp.lower().replace(":", ""), extra=cenv)
            ok(rc == 0 and "the root of 127.0.0.1 is saved" in out and os.path.isfile(os.path.join(trust, "127.0.0.1.pem")),
               "--pin with the root's fingerprint (typed loosely) saves the root", out[:300])
            ok(os.path.isdir(trust) and os.stat(trust).st_mode & 0o777 == 0o700
               and os.path.isfile(os.path.join(trust, "127.0.0.1.pem")) and os.stat(os.path.join(trust, "127.0.0.1.pem")).st_mode & 0o777 == 0o600,
               "the trust dir 0700, the file 0600")
            rc, out, _ = spark("client", extra=cenv)
            ok(rc == 0 and "peer" in out and ("up" in out or "ok" in out), "spark client: the other machine answers over TLS", out)
            status, value, _ = row(cenv)
            ok(status == "ok" and "127.0.0.1:%d trusted" % port2 in value, "the client's https row: trusted", (status, value))
            rc, out, _ = spark("client", "off", extra=cenv)
            ok(rc == 0 and "forgotten" in out and not os.listdir(trust), "spark client off forgets the trust", out)
            rc, out, _ = spark("client", url2, "--pin", leaf_fp, extra=cenv)
            ok(rc == 0 and "is pinned for 127.0.0.1" in out, "--pin with the page's own fingerprint pins the leaf", out[:300])
            ok(row(cenv)[0] == "ok", "the pinned leaf verifies")
            spark("client", "off", extra=cenv)
            rc, out, _ = spark("client", url2, "--ca", os.path.join(own, "root.crt"), extra=cenv)
            ok(rc == 0 and "saved for 127.0.0.1" in out and row(cenv)[0] == "ok", "--ca FILE saves the file as the host's trust", out[:300])
            rc, out, _ = spark("client", "http://127.0.0.1:9", "--pin", leaf_fp, extra=cenv)
            ok(rc == 2 and "plain http" in out, "--pin on a plain http URL is refused", out)
            spark("client", "off", extra=cenv)
        finally:
            stop(p)
        status, value, _ = row(oenv)
        ok(status == "ok", "the https row with the page down: the pair still reads", (status, value))
        rc, out, _ = spark("serve", "https", "off", extra=oenv)
        ok(rc == 0 and "plain http again" in out and "SPARK_FORGE_CERT=\n" in open(home + "/.config/spark/spark.env").read(),
           "spark serve https off: the keys cleared", out)
        rc, out, _ = spark("serve", "https", "off", extra=oenv)
        ok(rc == 0 and "already" in out, "off twice says so", out)
    finally:
        spark("serve", "https", "off")
        spark("forge", "off", "--force")


def page_units(ok):
    """The page's side without a server: the verbs it may run and the
    ones that end with its own restart, the https facts in each mode,
    the one-command restart through the unit, and the newest tag the
    checkout knows."""
    import re as _re
    from spark import REPO, config, forgeserve, qr, run, version
    rv = forgeserve.RUN_VERBS
    ok(rv["update"]([]) and rv["update"](["--dry-run"]) and not rv["update"](["--converge"]) and rv["serve"](["https", "own"])
       and not rv["serve"](["https", "off"]) and not rv["serve"](["https"]) and rv["serve"]([]) and rv["serve"](["--login", "--new"]),
       "RUN_VERBS: update (bare or --dry-run), and serve https own, are the page's; --converge, https off and bare https stay the terminal's")
    rs = forgeserve.RESTARTS
    ok(rs["update"]([]) and rs["serve"](["https", "own"]) and not rs["serve"](["--login", "--new"]) and "model" not in rs,
       "RESTARTS names the verbs whose stream ends with the page: update, serve https")

    class Cfg:
        forge_scheme, forge_cert, forge_name = "http", "", ""
    saved = (forgeserve.link_url, forgeserve.tls.is_own)
    try:
        forgeserve.link_url = lambda cfg, url=None: "http://192.0.2.9:8081"
        d = forgeserve.https_facts(Cfg())
        ok(d == {"mode": "off", "link": "http://192.0.2.9:8081/login"}, "https_facts over plain http: mode off, the page's link, nothing else", d)
        Cfg.forge_scheme, Cfg.forge_cert = "https", "/nowhere/leaf.crt"
        forgeserve.link_url = lambda cfg, url=None: "https://192.0.2.9:8081"
        forgeserve.tls.is_own = lambda c: True
        d = forgeserve.https_facts(Cfg())
        ok(d.get("mode") == "own" and d.get("link") == "https://192.0.2.9:8081/login" and d.get("ca") == "http://192.0.2.9:8082/ca"
           and d.get("ca_qr") == qr.encode("http://192.0.2.9:8082/ca"),
           "https_facts in own mode: the root's link on the port plus one, and its QR as qr.encode draws it", sorted(d))
        forgeserve.tls.is_own = lambda c: False
        d = forgeserve.https_facts(Cfg())
        ok(d.get("mode") == "pair" and "ca" not in d and "ca_qr" not in d, "https_facts with your pair: mode pair, no root", d)
    finally:
        forgeserve.link_url, forgeserve.tls.is_own = saved

    calls = []
    saved = (forgeserve.engine.forge_service_state, forgeserve.engine.kickstart, forgeserve._pid,
             forgeserve.cmd_stop, forgeserve.cmd_start, forgeserve.config.load)
    try:
        forgeserve.config.load = lambda: Cfg()
        forgeserve.engine.forge_service_state = lambda cfg, unit="forge": "loaded"
        forgeserve.engine.kickstart = lambda cfg, unit="serve", restart=False: calls.append(("kick", unit, restart)) or True
        forgeserve._pid = lambda: 4242
        forgeserve.cmd_stop = lambda a: calls.append(("stop", tuple(a))) or 0
        forgeserve.cmd_start = lambda a: calls.append(("start", tuple(a))) or 0
        rc = forgeserve._restart_page()
        ok(rc == 0 and calls == [("kick", "forge", True)],
           "_restart_page with a loaded unit: one restart through it, never a stop and then a start", (rc, calls))
        calls[:] = []
        forgeserve.engine.kickstart = lambda cfg, unit="serve", restart=False: calls.append(("kick", unit, restart)) and False
        ok(forgeserve._restart_page() == 1, "_restart_page: a restart the manager refused is rc 1")
        calls[:] = []
        forgeserve.engine.forge_service_state = lambda cfg, unit="forge": "none"
        rc = forgeserve._restart_page()
        ok(rc == 0 and calls == [("stop", ("--force",)), ("start", ())], "_restart_page by hand: stop --force, then start", (rc, calls))
        calls[:] = []
        forgeserve._pid = lambda: 0
        ok(forgeserve._restart_page() == 0 and calls == [], "_restart_page with nothing running: nothing", calls)
    finally:
        (forgeserve.engine.forge_service_state, forgeserve.engine.kickstart, forgeserve._pid,
         forgeserve.cmd_stop, forgeserve.cmd_start, forgeserve.config.load) = saved

    n = version.newest()
    rc, out = run(["git", "-C", REPO, "tag", "-l", "v[0-9]*", "--sort=-v:refname"])
    want = out.split()[0][1:] if rc == 0 and out.split() else ""
    ok(n == want and (n == "" or _re.match(r"^\d+\.\d+(\.\d+)?$", n)),
       "version.newest reads the newest v* tag as git sorts them, no subprocess", (n, want))


def main():
    fails = 0

    def ok(cond, what, extra=""):
        nonlocal fails
        print("  %s %s%s" % ("ok  " if cond else "FAIL", what, ("   " + str(extra)[:300]) if extra and not cond else ""))
        fails += not cond

    admin_boundary(ok)
    generation_admission(ok)
    reply_interruptions(ok)
    verb_runner(ok)
    page_units(ok)

    stub = HTTPServer(("127.0.0.1", 0), Peek)
    threading.Thread(target=stub.serve_forever, daemon=True).start()
    stub_url = "http://127.0.0.1:%d" % stub.server_address[1]

    with tempfile.TemporaryDirectory(prefix="spark-forge-") as tmp:
        home = os.path.join(tmp, "home")
        bins = os.path.join(tmp, "bin")
        state = os.path.join(home, ".local", "state", "spark")
        for d in (home, bins, os.path.join(home, ".config", "spark"), state):
            os.makedirs(d)
        os.chmod(state, 0o700)
        for name in ("launchctl", "systemctl"):
            with open(os.path.join(bins, name), "w") as f:
                f.write("#!/bin/sh\nexit 1\n")
            os.chmod(os.path.join(bins, name), 0o755)
        # a tool that refuses an option, and a man that documents it: the
        # page's /api/do/run carries the man excerpt as the prompt does
        for name, body in (("fakeflag", "#!/bin/sh\necho \"fakeflag: unrecognized option '$1'\"\nexit 2\n"),
                           ("man", "#!/bin/sh\nprintf 'OPTIONS\\n     --frob  never an option here\\n'\n")):
            with open(os.path.join(bins, name), "w") as f:
                f.write(body)
            os.chmod(os.path.join(bins, name), 0o755)
        with open(os.path.join(home, ".config", "spark", "soul"), "w") as f:
            f.write("Call yourself Fixture.\n")
        os.chmod(os.path.join(home, ".config", "spark", "soul"), 0o600)
        with open(os.path.join(state, "serve-url"), "w") as f:
            f.write(stub_url + "\n")
        port = free_port()
        url = "http://127.0.0.1:%d" % port
        env = {k: v for k, v in os.environ.items() if not k.startswith(("SPARK_", "XDG_", "SITE_"))}
        env.update({"HOME": home, "XDG_CONFIG_HOME": home + "/.config", "XDG_STATE_HOME": home + "/.local/state",
                    "XDG_DATA_HOME": home + "/.local/share", "PATH": bins + ":" + env.get("PATH", ""),
                    "SPARK_SERVE_HOST": "127.0.0.1", "SPARK_API_KEY": smoke.TOKEN,
                    "SPARK_FORGE_HOST": "127.0.0.1", "SPARK_FORGE_PORT": str(port),
                    "SPARK_NO_APPLY": "1", "SPARK_NO_REFRESH": "1", "SPARK_SERVICE": "none", "SPARK_TIMEOUT": "5",
                    "SITE_NAME": "fixture", "SHELL": "/bin/bash", "TERM": "xterm-256color",
                    "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"})

        env.update(smoke.init_env(tmp))

        def spark(*args, extra=None, stdin="", timeout=60):
            e = dict(env)
            e.update(extra or {})
            p = subprocess.run([sys.executable, SPARK] + list(args), input=stdin, capture_output=True, text=True, env=e, timeout=timeout)
            return p.returncode, p.stdout, p.stderr

        print("forge_smoke: stub llama-server at %s, forge at %s, HOME %s" % (stub_url, url, home))

        # refusals before anything binds
        rc, out, err = spark("forge", "--foreground", "--host", "0.0.0.0")
        ok(rc == 78 and "0.0.0.0" in err, "--foreground --host 0.0.0.0 -> 78", err)
        rc, out, err = spark("forge", "--foreground", "--host", "0")
        ok(rc == 78 and "0 is 0.0.0.0, every interface" in err, "--foreground --host 0 (the short spelling) -> 78", err)
        rc, out, err = spark("forge", "--foreground", extra={"SPARK_FORGE_TOKEN": "short"})
        ok(rc == 2 and "spark forge -- SPARK_FORGE_TOKEN is shorter than 32 characters: refused" in out + err,
           "a SPARK_FORGE_TOKEN shorter than 32 characters is refused, exit 2", out + err)
        from spark import bind_check as _bc
        ok(all(_bc(h)[0] == "refuse" for h in ("0", "0.0", "00.0.0.0", "0.0.0.0", "::")),
           "bind_check refuses every spelling of the unspecified address")
        ok(all(_bc(h) == ("", "") for h in ("192.0.2.10", "127.0.0.1", "::1", "localhost", "")),
           "bind_check passes a LAN address, loopback, a hostname")
        ok(_bc("8.8.8.8")[0] == "warn", "bind_check warns on a public address", _bc("8.8.8.8"))
        rc, out, err = spark("forge", "-h")
        ok(rc == 0 and out.splitlines()[0] == "spark forge -- run the page's server", "spark forge -h signs (contract 8)", out)
        ok(all(len(l) <= 80 for l in out.splitlines()), "usage fits 80 columns")
        rc, out, _ = spark("forge")
        ok(rc == 0 and "not running" in out, "status before start: not running", out)
        rc, out, _ = spark("forge", "off")
        ok(rc == 0 and "not running" in out, "stop before start: not running, exit 0", out)

        # the server, in the foreground
        p = subprocess.Popen([sys.executable, "-c", FORGE_WRAP, os.path.join(REPO, "lib"), SPARK, "forge", "--foreground"],
                             env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        deadline = time.time() + 20
        st = 0
        while time.time() < deadline and st != 200:
            try:
                st, _, raw = req(url, "GET", "/api/health", timeout=2)
            except OSError:
                st = 0
            if st != 200:
                time.sleep(0.3)
        try:
            ok(st == 200, "--foreground answers /api/health")
            if st == 200:
                # the same probes the hardening row and tests/forge_probe.py run
                for name, held, detail in forge_probe.probe(url):
                    ok(held, "gate: " + name, detail)
            if st != 200:
                p.kill()
                print(p.communicate()[0][-2000:])
                return 1
            h = json.loads(raw)
            ok(h.get("forge") is True and h.get("status") == "ok" and h.get("name") == "fixture", "health: forge true, name", h)
            ok(h.get("model") == "stub-7b-q4" and h.get("upstream") == "ok", "health: the stub's model, upstream ok", h)
            ok(h.get("models") == {"spark": "loaded", "ember": "loaded"}, "health: models lists both roles, loaded", h)
            tok_path = state + "/forge-token"
            ok(os.path.isfile(tok_path) and oct(os.stat(tok_path).st_mode & 0o777) == "0o600", "forge-token 0600")
            token = open(tok_path).read().strip()
            rc0, out0, _ = spark("user", "add", "owner")
            ok(rc0 == 0 and "this machine is owner" in out0, "the box's own account minted and logged in", out0)
            rc0, out0, _ = spark("user", "add", "ualice", "--show-token")
            utoken = next((l.strip() for l in out0.splitlines() if len(l.strip()) >= 40 and " " not in l.strip()), "")
            ok(rc0 == 0 and utoken and "this machine is ualice" not in out0,
               "spark user add ualice: token shown once, login untouched", out0)
            rc0, out0, _ = spark("user", "add", "ubob", "--show-token")
            btoken = next((l.strip() for l in out0.splitlines() if len(l.strip()) >= 40 and " " not in l.strip()), "")
            ok(rc0 == 0 and btoken and btoken != utoken, "a second user, its own token", out0)
            ok(open(state + "/forge-url").read().strip() == url, "forge-url written")
            ok(int(open(state + "/forge.pid").read()) == p.pid, "forge.pid is the foreground pid")
            bearer = {"Authorization": "Bearer " + token}
            ubearer = {"Authorization": "Bearer " + utoken}
            XS = {"X-Spark": "1"}             # the write gate: a login goes through it too

            def login(tok, **kw):
                return req(url, "POST", "/api/login", {"token": tok}, headers=XS, **kw)

            # auth
            st, h, raw = req(url, "GET", "/api/check")
            ok(st == 401 and h.get("Cache-Control") == "no-store", "/api/check bare -> 401, no-store", (st, h))
            st, _, _ = req(url, "GET", "/api/check", headers={"Authorization": "Bearer nope"})
            ok(st == 401, "wrong bearer -> 401")
            t0 = time.time()
            st, _, _ = login("nope")
            ok(st == 401 and time.time() - t0 >= 1.0, "wrong login -> 401 after >= 1 s (%.1f s)" % (time.time() - t0))
            # a non-ASCII token is a WRONG token, never a 500: the compare
            # runs over bytes, so the 1 s cost and the counter still apply
            t0 = time.time()
            st, _, raw = login("café-token")
            ok(st == 401 and time.time() - t0 >= 1.0,
               "a non-ASCII token login -> 401 after >= 1 s, not a 500", (st, raw[:80]))
            st, _, _ = req(url, "GET", "/api/check", headers={"Authorization": "Bearer café"})
            ok(st == 401, "a non-ASCII bearer -> 401, not a 500", st)
            st, _, _ = req(url, "GET", "/api/check", headers={"Cookie": "spark_forge=café"})
            ok(st == 401, "a non-ASCII cookie -> 401, not a 500", st)
            # the handler carries a socket timeout, and the login sleep is
            # bounded: a burst of wrong logins cannot hold 100 threads
            from spark import forgeserve as _fsv
            ok(_fsv.Handler.timeout == 30, "the handler carries a 30 s socket timeout")
            ok(getattr(_fsv._PUNISH, "_initial_value", None) == 8,
               "the login punish sleep is bounded by a semaphore of 8")
            st, h, raw = login(token)
            sc = h.get("Set-Cookie", "")
            ok(st == 200 and sc.startswith("spark_forge=") and "HttpOnly" in sc and "SameSite=Strict" in sc and "Max-Age=7776000" in sc,
               "right login -> cookie HttpOnly, SameSite=Strict, 90 days", sc)
            cookie = {"Cookie": sc.split(";")[0]}
            st, _, raw = req(url, "GET", "/api/me", headers=cookie)
            d = json.loads(raw)
            ok(st == 200 and d.get("role") == "admin" and d.get("name") == "fixture" and d.get("version"),
               "/api/me with the admin cookie: role admin, name, version", raw[:100])
            st, _, raw = req(url, "GET", "/api/me", headers=bearer)
            ok(st == 200 and json.loads(raw).get("role") == "admin", "/api/me with the admin bearer: role admin", raw[:100])
            # the login goes through the write gate like every other POST:
            # a page on another origin cannot log a browser in
            st, _, _ = req(url, "POST", "/api/login", {"token": token})
            ok(st == 403, "login without X-Spark -> 403 (the write gate)", st)
            st, _, _ = req(url, "POST", "/api/login", {"token": token}, headers=dict(XS, Origin="http://evil.example"))
            ok(st == 403, "login with a foreign Origin -> 403", st)
            st, _, raw = req(url, "POST", "/api/login", {"token": token}, headers=dict(XS, **{"Content-Type": "text/plain"}))
            ok(st == 415 and json.loads(raw)["error"]["kind"] == "bad", "login with a text/plain body -> 415", (st, raw[:80]))
            # a session is minted, never derived: two logins, two cookies,
            # neither computable from the token, and a logout kills its own
            st, h2, _ = login(token)
            cookie2 = {"Cookie": h2.get("Set-Cookie", "").split(";")[0]}
            ok(st == 200 and cookie2["Cookie"] != cookie["Cookie"] and token not in cookie2["Cookie"],
               "a second admin login: a different cookie, not the token", (cookie["Cookie"][:30], cookie2["Cookie"][:30]))
            st, _, raw = req(url, "GET", "/api/me", headers=cookie2)
            ok(st == 200 and json.loads(raw).get("role") == "admin", "the second admin cookie works", raw[:80])
            st, _, _ = req(url, "POST", "/api/logout", {}, headers=dict(cookie2, **XS))
            ok(st == 200, "the admin logs the second one out", st)
            st, _, _ = req(url, "GET", "/api/me", headers=cookie2)
            ok(st == 401, "the logged-out admin cookie replayed -> 401 (its session died)", st)
            st, _, _ = req(url, "GET", "/api/me", headers=cookie)
            ok(st == 200, "the first admin cookie is untouched by the other's logout", st)
            with open(state + "/check.json", "w") as f:
                json.dump({"ts": int(time.time()) - 5, "name": "fixture", "version": "0", "counts": {"ok": 1, "fail": 0, "warn": 0, "na": 0},
                           "rows": [{"category": "SOFTWARE", "status": "ok", "name": "x", "value": "y", "remedy": ""}]}, f)
            st, h, raw = req(url, "GET", "/api/check", headers=cookie)
            d = json.loads(raw)
            ok(st == 200 and d["counts"]["ok"] == 1 and isinstance(d.get("age"), int), "cookie reads /api/check (with age)", (st, raw[:100]))
            ok(d.get("rows") and d.get("name") == "fixture" and h.get("X-Content-Type-Options") == "nosniff",
               "the admin's /api/check is check.json whole (rows, name), nosniff", (raw[:120], h))
            st, h, raw = req(url, "GET", "/api/check", headers=ubearer)
            d = json.loads(raw)
            ok(st == 200 and sorted(d) == ["age", "counts", "ts"] and d["counts"]["ok"] == 1
               and isinstance(d["age"], int) and h.get("X-Content-Type-Options") == "nosniff",
               "a user's /api/check: the counts alone -- no rows, no names, no sends", (st, raw[:120]))
            st, _, raw = req(url, "GET", "/api/stats?days=7", headers=bearer)
            d = json.loads(raw)
            ok(st == 200 and "tg_mean" in d and "baseline" in d and "running" in d, "bearer reads /api/stats", raw[:100])
            st, _, _ = req(url, "GET", "/api/stats?days=2", headers=bearer)
            ok(st == 400, "days=2 -> 400")
            st, _, _ = req(url, "POST", "/api/check/refresh", {}, headers=bearer)
            ok(st == 403, "POST without X-Spark -> 403", st)
            st, _, _ = req(url, "POST", "/api/check/refresh", {}, headers=dict(bearer, **{"X-Spark": "1", "Host": "evil.example:1"}))
            ok(st == 400, "wrong Host -> 400", st)
            st, _, _ = req(url, "POST", "/api/check/refresh", {}, headers=dict(bearer, **{"X-Spark": "1", "Origin": "http://evil.example"}))
            ok(st == 403, "foreign Origin -> 403", st)
            st, _, _ = req(url, "POST", "/api/check/refresh", {}, headers=dict(bearer, **{"X-Spark": "1", "Origin": url}))
            ok(st == 202, "POST /api/check/refresh with X-Spark and a same-host Origin -> 202", st)
            st, _, _ = req(url, "POST", "/api/check/refresh", {}, headers=dict(bearer, **{"X-Spark": "1", "Host": "localhost:%d" % port}))
            ok(st == 202, "Host localhost:PORT is this machine", st)
            st, _, _ = req(url, "GET", "/api/nope", headers=bearer)
            ok(st == 404, "unknown /api route -> 404")

            # the OpenAI-compatible face: identity in, api-token on
            SEEN.clear()
            st, h, raw = req(url, "POST", "/v1/chat/completions", {"messages": [{"role": "user", "content": "capital of France?"}], "stream": False}, headers=bearer)
            d = json.loads(raw)
            ok(st == 200 and "Paris" in d["choices"][0]["message"]["content"], "non-stream chat: the stub's JSON comes back", raw[:200])
            sys0 = SEEN.get("body", {}).get("messages", [{}])[0]
            ok(sys0.get("role") == "system" and "Call yourself Fixture." in sys0.get("content", ""), "the stub saw the soul in messages[0]", str(sys0)[:200])
            ok("You are spark, the assistant at" in sys0.get("content", ""), "no client system message: the forge's own is inserted", str(sys0)[:200])
            ok(SEEN.get("body", {}).get("model") == "ember", "no model in the request: ember goes upstream", SEEN.get("body", {}).get("model"))
            ok(SEEN.get("auth") == "Bearer " + smoke.TOKEN, "the api-token went upstream, not the forge token", SEEN.get("auth"))
            SEEN.clear()
            st, _, raw = req(url, "POST", "/v1/chat/completions",
                             {"messages": [{"role": "system", "content": "PREFIX-MARK"}, {"role": "user", "content": "what"}], "stream": False}, headers=bearer)
            c = SEEN.get("body", {}).get("messages", [{}])[0].get("content", "")
            ok(st == 200 and c.startswith("Call yourself Fixture.") and c.endswith("PREFIX-MARK"), "a client prefix comes after the identity", c[:200])
            SEEN.clear()
            st, _, raw = req(url, "POST", "/v1/chat/completions",
                             {"model": "spark", "messages": [{"role": "system", "content": "LINE-MARK"}, {"role": "user", "content": "what"}], "stream": False}, headers=bearer)
            c = SEEN.get("body", {}).get("messages", [{}])[0].get("content", "")
            ok(st == 200 and SEEN.get("body", {}).get("model") == "spark" and c == "LINE-MARK" and "Fixture" not in json.dumps(SEEN.get("body", {})),
               "model spark: passed through, the client's system message untouched, no identity", c[:200])
            SEEN.clear()
            st, _, raw = req(url, "POST", "/v1/chat/completions",
                             {"model": "ember", "messages": [{"role": "system", "content": "PREFIX-MARK"}, {"role": "user", "content": "what"}], "stream": False}, headers=bearer)
            c = SEEN.get("body", {}).get("messages", [{}])[0].get("content", "")
            ok(st == 200 and SEEN.get("body", {}).get("model") == "ember" and c.startswith("Call yourself Fixture."),
               "model ember explicit: the identity goes in", c[:200])
            # v1.78: only the served roles route -- spark, ember, or a
            # role's stem or name as /api/health shows it; the role goes up
            _st, _, _hraw = req(url, "GET", "/api/health")
            _roles = json.loads(_hraw).get("roles") or {}
            for _name, _role in ((_roles.get("ember"), "ember"), (_roles.get("spark"), "spark")):
                SEEN.clear()
                st, _, raw = req(url, "POST", "/v1/chat/completions",
                                 {"model": _name, "messages": [{"role": "user", "content": "what"}], "stream": False},
                                 headers=bearer)
                c = json.dumps(SEEN.get("body", {}))
                ok(st == 200 and bool(_name) and SEEN.get("body", {}).get("model") == _role
                   and ("Call yourself Fixture." in c) == (_role == "ember"),
                   "model %r (the %s role's stem): %s goes upstream" % (_name, _role, _role), (st, c[:200]))
            for _bad in ("gpt-4", "../ember", "Ember", 5, ["ember"], {"x": 1}):
                SEEN.clear()
                st, _, raw = req(url, "POST", "/v1/chat/completions",
                                 {"model": _bad, "messages": [{"role": "user", "content": "what"}], "stream": False},
                                 headers=bearer)
                ok(st == 400 and json.loads(raw)["error"]["kind"] == "model" and not SEEN,
                   "model %r is no role served here -> 400 model, nothing upstream" % (_bad,), (st, raw[:200]))
            SEEN.clear()
            st, _, raw = req(url, "POST", "/v1/chat/completions",
                             {"model": "", "messages": [{"role": "user", "content": "what"}], "stream": False}, headers=bearer)
            ok(st == 200 and SEEN.get("body", {}).get("model") == "ember", "model empty: ember, as when missing", st)
            # "identity": false asks for the chat model bare
            SEEN.clear()
            st, _, raw = req(url, "POST", "/v1/chat/completions",
                             {"model": "ember", "identity": False, "messages": [{"role": "system", "content": "OWN-PERSONA"}, {"role": "user", "content": "what"}], "stream": False}, headers=bearer)
            sb = SEEN.get("body", {})
            ok(st == 200 and sb.get("model") == "ember" and sb.get("messages") == [{"role": "system", "content": "OWN-PERSONA"}, {"role": "user", "content": "what"}]
               and "Fixture" not in json.dumps(sb) and "identity" not in sb,
               "identity false: ember keeps the client's messages exactly, no soul, no identity key upstream", json.dumps(sb)[:200])
            SEEN.clear()
            st, _, raw = req(url, "POST", "/v1/chat/completions",
                             {"identity": False, "messages": [{"role": "user", "content": "what"}], "stream": False}, headers=bearer)
            sb = SEEN.get("body", {})
            ok(st == 200 and sb.get("model") == "ember" and sb.get("messages") == [{"role": "user", "content": "what"}] and "identity" not in sb,
               "identity false, no model: ember, and no system message is inserted", json.dumps(sb)[:200])
            SEEN.clear()
            st, _, raw = req(url, "POST", "/v1/chat/completions",
                             {"identity": True, "messages": [{"role": "system", "content": "PREFIX-MARK"}, {"role": "user", "content": "what"}], "stream": False}, headers=bearer)
            sb = SEEN.get("body", {})
            c = sb.get("messages", [{}])[0].get("content", "")
            ok(st == 200 and c.startswith("Call yourself Fixture.") and c.endswith("PREFIX-MARK") and "identity" not in sb,
               "identity true: the identity goes in, and the key stays here", c[:200])
            for bad in ("no", 0, None, [False]):
                SEEN.clear()
                st, _, raw = req(url, "POST", "/v1/chat/completions",
                                 {"identity": bad, "messages": [{"role": "user", "content": "what"}], "stream": False}, headers=bearer)
                ok(st == 400 and json.loads(raw) == {"error": {"kind": "bad", "hint": "identity is true or false"}} and not SEEN,
                   "identity %r -> 400, nothing upstream" % (bad,), raw[:200])
            st, h, raw = req(url, "POST", "/v1/chat/completions", {"messages": [{"role": "user", "content": "what"}], "stream": True}, headers=bearer)
            text = raw.decode()
            ok(st == 200 and h.get("Content-Type", "").startswith("text/event-stream") and text.count("data:") >= 5 and "[DONE]" in text,
               "stream chat: the SSE deltas pass through", text[:200])
            st, _, _ = req(url, "POST", "/v1/chat/completions", {"messages": "x"}, headers=bearer)
            ok(st == 400, "messages not a list -> 400")
            # the bearer only: a browser's cookie does not open the model
            st, _, _ = req(url, "POST", "/v1/chat/completions", {"messages": [{"role": "user", "content": "what"}], "stream": False}, headers=cookie)
            ok(st == 401, "/v1/chat/completions with a cookie only -> 401", st)
            # the forwarded request asks for at most V1_MAX_TOKENS
            for asked, expect in ((None, 8192), (99999, 8192), (-1, 8192), (100, 100)):
                SEEN.clear()
                vb = {"messages": [{"role": "user", "content": "what"}], "stream": False}
                if asked is not None:
                    vb["max_tokens"] = asked
                req(url, "POST", "/v1/chat/completions", vb, headers=bearer)
                ok(SEEN.get("body", {}).get("max_tokens") == expect,
                   "max_tokens %s goes upstream as %d" % (asked, expect), SEEN.get("body", {}).get("max_tokens"))
            SEEN.clear()
            req(url, "POST", "/v1/chat/completions", {"messages": [{"role": "user", "content": "what"}], "stream": False, "n_predict": -1}, headers=bearer)
            ok(SEEN.get("body", {}).get("n_predict") == 8192, "n_predict -1 (no limit upstream) is capped too", SEEN.get("body", {}).get("n_predict"))
            st, _, raw = req(url, "GET", "/v1/models", headers=bearer)
            models = (json.loads(raw) if st == 200 else {}).get("data", [])
            ok(st == 200 and [(m.get("id"), m.get("aliases"), m.get("status")) for m in models]
               == [("stub-7b-q4", ["spark"], {"value": "loaded"}), ("stub-ember-q4", ["ember"], {"value": "loaded"})]
               and "/" not in raw.decode() and ".gguf" not in raw.decode(),
               "/v1/models: one entry a served role, the file's stem as id, never a path or the engine's own listing", raw[:200])

            # the monitor: the status line card left the page with v1.97
            st, _, _ = req(url, "GET", "/api/bar", headers=bearer, timeout=30)
            ok(st == 404, "/api/bar is gone (v1.97: the status line card left the page) -> 404", st)
            # what left this machine: the rows of spark stats --sends, for the window
            st, _, raw = req(url, "GET", "/api/stats?days=7", headers=bearer, timeout=30)
            d = json.loads(raw)
            ok(st == 200 and d.get("days") == 7 and isinstance(d.get("sends"), list)
               and all(set(r) == {"day", "dest", "bytes", "turns"} and isinstance(r["bytes"], int) for r in d["sends"]),
               "/api/stats carries sends: day, dest, bytes, turns a row (%d rows)" % len(d.get("sends") or []), raw[:200])
            st, _, raw = req(url, "GET", "/api/stats?days=1", headers=ubearer, timeout=30)
            ok(st == 200 and isinstance(json.loads(raw).get("sends"), list), "/api/stats answers a user with sends too", raw[:100])
            # /api/models: the box's table for a client's `spark model`, any role
            st, _, raw = req(url, "GET", "/api/models", headers={"Authorization": "Bearer " + utoken}, timeout=30)
            dm = json.loads(raw)
            ok(st == 200 and dm.get("name") == "fixture" and dm.get("total_gb", 0) > 0 and dm.get("backend")
               and isinstance(dm.get("models"), list) and dm["models"] and "fits" in dm["models"][0],
               "/api/models (a user): name, total_gb, backend, the rows with a verdict", raw[:200])
            ok(token not in raw.decode() and utoken not in raw.decode() and home not in raw.decode(), "/api/models carries no token, no path")
            # the table follows site.env as it is NOW: `spark model NAME` restarts
            # spark-serve, not the forge, and the forge used to answer from the
            # config it started with (the star stayed on the old pick)
            site_env = os.path.join(home, ".config", "spark", "site.env")
            site_was = open(site_env).read() if os.path.exists(site_env) else None

            def pick_after(name, when):
                with open(site_env, "w") as f:
                    f.write("SITE_AI_MODEL=%s\n" % name)
                os.utime(site_env, (when, when))
                st, _, raw = req(url, "GET", "/api/models", headers={"Authorization": "Bearer " + utoken}, timeout=30)
                return st, [r["name"] for r in json.loads(raw)["models"] if r.get("role") == "spark"]
            st1, pick1 = pick_after("qwen3-5-2b", time.time() + 5)
            st2, pick2 = pick_after("qwen3-4b", time.time() + 10)
            ok(st1 == 200 and pick1 == ["qwen3-5-2b"] and st2 == 200 and pick2 == ["qwen3-4b"],
               "/api/models follows site.env without a restart (the pick moved)", "%s -> %s" % (pick1, pick2))
            if site_was is None:
                os.remove(site_env)
            else:
                with open(site_env, "w") as f:
                    f.write(site_was)
            rc0, out0, _ = spark("model", extra={"SITE_AI_MODEL": "none", "SITE_PEER_AI_URL": url,
                                                 "SPARK_FORGE_TOKEN": utoken, "SPARK_MEM_TOTAL_GB": "1"})
            head0 = " ".join(out0.splitlines()[:2])
            ok(rc0 == 0 and "a client of " + url in head0 and "the other machine's table" in head0 and "%.0f GB for models" % dm["total_gb"] in head0
               and " 1 GB" not in head0,
               "spark model on a client of this FORGE prints the other machine's table, not its own 1 GB", out0[:300])
            ok(any(ln.endswith("tok/s") or ln.endswith("too big") for ln in out0.splitlines()), "the peer's rows carry the peer's verdicts", out0[:300])
            # /api/config with a spark.env naming the secret files (the real
            # paths, so the running forge keeps its token) and a key with
            # TOKEN in its name the reader accepts as it is
            spark_env = os.path.join(home, ".config", "spark", "spark.env")
            spark_was = open(spark_env).read() if os.path.exists(spark_env) else None
            with open(spark_env, "w") as f:
                f.write("SPARK_API_KEY_FILE=%s/api-token\nSPARK_FORGE_TOKEN_FILE=%s/forge-token\nSPARK_PAGE_TOKEN=abc\n"
                        "SPARK_LOOK_MOTION=on\n" % (state, state))   # a key v1.69 removed: it loads, ignored
            st, _, raw = req(url, "GET", "/api/config", headers=bearer, timeout=30)
            d = json.loads(raw)

            def keys(x, acc):
                if isinstance(x, dict):
                    for k, v in x.items():
                        acc.append(k)
                        keys(v, acc)
                elif isinstance(x, list):
                    for v in x:
                        keys(v, acc)
                return acc
            ks = keys(d, [])
            ok(st == 200 and "themes" not in d and "models" in d and "effective" in d
               and not any(k in d["effective"] for k in ("SITE_THEME", "SITE_FONT_FACE", "SITE_QUIET_BOOT",
                                                          "SITE_QUIET_START", "SITE_QUIET_AUDIO", "SPARK_LOOK_MOTION"))
               and "SPARK_LOOK" in d["effective"],
               "/api/config: models, effective (SPARK_LOOK); no palettes, no removed keys", raw[:200])
            hf = d.get("https") or {}
            ok(isinstance(hf, dict) and hf.get("mode") == "off" and hf.get("link", "").endswith("/login") and "ca" not in hf,
               "/api/config carries https: mode off, the page's link, no root over plain http", hf)
            secret = [k for k in ks if re.search("KEY|TOKEN|SECRET", k)]
            ok(not secret, "/api/config never names a key matching KEY|TOKEN|SECRET (spark.env holds three)", secret)
            ok(token not in raw.decode() and smoke.TOKEN not in raw.decode() and "forge-token" not in raw.decode()
               and "api-token" not in raw.decode(), "/api/config carries no token value, no token file path")
            if spark_was is None:
                os.remove(spark_env)
            else:
                with open(spark_env, "w") as f:
                    f.write(spark_was)
            st, _, _ = req(url, "GET", "/api/theme", headers=bearer)
            ok(st == 404, "/api/theme is gone (v1.62: the look left core) -> 404", st)
            st, _, raw = req(url, "GET", "/api/serve", headers=bearer)
            d = json.loads(raw)
            ok(st == 200 and d["url"] == stub_url and d["health"] == "ok" and d["model"] == "stub-7b-q4" and "log" not in d,
               "/api/serve sees the upstream, and carries no log tail (v1.97)", raw[:200])
            st, _, raw = req(url, "GET", "/api/gpu", headers=bearer)
            ok(st == 200 and isinstance(json.loads(raw), dict), "/api/gpu")
            st, _, raw = req(url, "GET", "/api/bench", headers=bearer)
            d = json.loads(raw)
            ok(st == 200 and "now" in d and "baseline" in d and "tune" in d, "/api/bench", raw[:100])
            # the request line lands after the response left (it carries the
            # time taken), and the server is threaded: give it a moment.
            # The window has to be wider than the poll can fill -- every
            # poll writes a log line of its own, so waiting on a tail of 3
            # pushes the line being waited for out of its own window the
            # moment the server is slow enough to need a second look.
            st, _, _ = req(url, "GET", "/api/log?n=30", headers=bearer)
            ok(st == 404, "/api/log is gone (v1.97: nothing on the page read it) -> 404", st)
            lg = open(state + "/forge.log").read()
            ok(oct(os.stat(state + "/forge.log").st_mode & 0o777) == "0o600" and token not in lg and smoke.TOKEN not in lg, "forge.log 0600, no token in it")
            ok("login failed" in lg and "wrong bearer" in lg, "forge.log has the login events", lg[-300:])
            # events: the first bytes carry the snapshot
            u = urllib.parse.urlsplit(url)
            c = http.client.HTTPConnection(u.hostname, u.port, timeout=10)
            c.request("GET", "/api/events", None, bearer)
            r = c.getresponse()
            head = ""
            while "event: serve" not in head and len(head) < 4000:
                line = r.readline().decode()
                if not line:
                    break
                head += line
            c.close()
            ok(r.status == 200 and "event: check" in head and "event: serve" in head
               and "event: bar" not in head and "event: log" not in head,
               "/api/events opens with check and serve, and no bar or log event (v1.97)", head[:200])
            # a browser that hangs up mid-stream must not kill the server
            # (bin/spark sets SIGPIPE to SIG_DFL for pipes; the forge ignores it)
            import socket as _socket
            c = http.client.HTTPConnection(u.hostname, u.port, timeout=10)
            c.request("POST", "/api/chat", json.dumps({"text": "count"}).encode(),
                      dict(bearer, **{"X-Spark": "1", "Origin": url, "Content-Type": "application/json"}))
            sk = c.sock
            r = c.getresponse()
            r.read(1)
            sk.setsockopt(_socket.SOL_SOCKET, _socket.SO_LINGER,
                          __import__("struct").pack("ii", 1, 0))
            sk.close()
            time.sleep(1.0)
            st, _, raw = req(url, "GET", "/api/health")
            ok(st == 200 and b"forge" in raw, "the forge outlives a client that hung up mid-stream", st)
            for f in __import__("glob").glob(state + "/users/*/threads/*.sealed"):
                os.remove(f)  # the hung-up chat's thread; later cases start clean
            # the header's food: /api/health names each role's model
            st, _, raw = req(url, "GET", "/api/health")
            hj = json.loads(raw)
            ok(st == 200 and hj.get("roles", {}).get("spark") and hj.get("roles", {}).get("ember"),
               "/api/health carries roles with each model's stem", hj.get("roles"))
            st, _, raw = req(url, "POST", "/api/chat", {"text": "count"},
                             headers=dict(bearer, **{"X-Spark": "1", "Origin": url, "Content-Type": "application/json"}), timeout=30)
            dn = [d for e, d in sse(raw) if e == "done"]
            ok(hj.get("names", {}).get("ember") and set(hj.get("names", {})) == set(hj.get("roles", {})),
               "/api/health carries names: each role's model by its name in the list", hj.get("names"))
            ok(st == 200 and dn and dn[0].get("model") == hj["names"]["ember"],
               "the chat's done event names the ember's model by its name", dn)
            for f in __import__("glob").glob(state + "/users/*/threads/*.sealed"):
                os.remove(f)

            # the page, when the sibling has written it
            if os.path.isfile(os.path.join(REPO, "lib", "spark", "forge", "index.html")):
                st, h, raw = req(url, "GET", "/")
                ok(st == 200 and h.get("Content-Type", "").startswith("text/html") and h.get("Content-Security-Policy") == "default-src 'self'"
                   and h.get("X-Frame-Options") == "DENY" and h.get("X-Content-Type-Options") == "nosniff" and "ETag" in h,
                   "GET / is the page with CSP, DENY, nosniff", (st, h))
                st, _, _ = req(url, "GET", "/", headers={"If-None-Match": h["ETag"]})
                ok(st == 304, "ETag round trip -> 304")
                st, _, _ = req(url, "GET", "/login")
                ok(st == 200, "/login is the page too")
            st, _, _ = req(url, "GET", "/static/../__init__.py")
            ok(st == 404, "no path traversal under /static/", st)
            st, _, _ = req(url, "GET", "/static/nope.js")
            ok(st == 404, "unknown static name -> 404")

            # the standalone face: manifest, favicon, the drawn touch icon
            # (the two files ride with the page; the icon is always there)
            if os.path.isfile(os.path.join(REPO, "lib", "spark", "forge", "manifest.webmanifest")):
                st, h, raw = req(url, "GET", "/manifest.webmanifest")
                d = {}
                try:
                    d = json.loads(raw)
                except ValueError:
                    pass
                ok(st == 200 and h.get("Content-Type", "").startswith("application/manifest+json")
                   and d.get("start_url") == "/", "/manifest.webmanifest: 200, its type, start_url /, no token", (st, h, raw[:200]))
                st, _, _ = req(url, "GET", "/manifest.webmanifest", headers={"If-None-Match": h.get("ETag", "")})
                ok(st == 304, "manifest ETag round trip -> 304", st)
            if os.path.isfile(os.path.join(REPO, "lib", "spark", "forge", "favicon.svg")):
                st, h, raw = req(url, "GET", "/static/favicon.svg")
                ok(st == 200 and h.get("Content-Type", "").startswith("image/svg+xml"),
                   "/static/favicon.svg: 200, image/svg+xml, no token", (st, h))
            st, h, raw = req(url, "GET", "/apple-touch-icon.png")
            dims = struct.unpack(">II", raw[16:24]) if len(raw) >= 24 else (0, 0)
            ok(st == 200 and h.get("Content-Type") == "image/png" and raw[:8] == b"\x89PNG\r\n\x1a\n" and dims == (180, 180),
               "/apple-touch-icon.png: 200, a real 180x180 PNG, no token", (st, h.get("Content-Type"), dims))
            st, _, _ = req(url, "GET", "/apple-touch-icon.png", headers={"If-None-Match": h.get("ETag", "")})
            ok(st == 304, "touch icon ETag round trip -> 304", st)


            # the page's food: threads, chat, soul, memory, do, the verb runner
            post = dict(bearer, **{"X-Spark": "1", "Origin": url})
            st, _, raw = req(url, "GET", "/api/threads?n=30", headers=bearer)
            ok(st == 200 and json.loads(raw) == {"threads": []}, "/api/threads: empty at first", raw[:100])
            SEEN.clear()
            st, h, raw = req(url, "POST", "/api/chat", {"text": "count"}, headers=post, timeout=30)
            evs = sse(raw)
            deltas = "".join(d["t"] for e, d in evs if e == "delta")
            done = [d for e, d in evs if e == "done"]
            ok(st == 200 and h.get("Content-Type", "").startswith("text/event-stream") and h.get("Cache-Control") == "no-store",
               "/api/chat answers SSE, no-store", (st, h))
            ok(deltas == "2" and done and done[0].get("thread") and isinstance(done[0].get("ms"), int),
               "chat: the deltas join to the stub's answer (system + line = 2), done names a thread", evs)
            ok(SEEN.get("auth") == "Bearer " + smoke.TOKEN, "chat went upstream with the api-token, not back into the forge", SEEN.get("auth"))
            sys0 = SEEN.get("body", {}).get("messages", [{}])[0].get("content", "")
            ok(sys0.startswith("You are on ") and "Call yourself Fixture." in sys0 and "This is a conversation" in sys0,
               "chat: an in-process reply carries the machine line, identity and the chat mode", sys0[:200])
            ok("Preferred when installed" not in sys0 and "Flags that exist" not in sys0,
               "chat through the forge sheds the shell costume", sys0[:200])
            ok(SEEN.get("body", {}).get("model") == "ember", "chat goes upstream as the ember", SEEN.get("body", {}).get("model"))
            tid = done[0]["thread"] if done else ""
            tpaths = __import__("glob").glob(state + "/users/*/threads/" + tid + ".sealed")
            tpath = tpaths[0] if tpaths else ""
            ok(bool(tpath) and oct(os.stat(tpath).st_mode & 0o777) == "0o600"
               and open(tpath, "rb").read(23) == b"spark-sealed-v1 thread ",
               "the thread file exists, 0600, sealed", tpath)
            st, _, raw = req(url, "GET", "/api/threads", headers=bearer)
            d = json.loads(raw)
            ok(st == 200 and len(d["threads"]) == 1 and d["threads"][0]["id"] == tid and d["threads"][0]["turns"] == 1, "/api/threads lists it with 1 turn", raw[:200])
            st, _, raw = req(url, "GET", "/api/threads/" + tid, headers=cookie)
            d = json.loads(raw)
            ok(st == 200 and d["id"] == tid and [m["role"] for m in d["messages"]] == ["user", "assistant"] and d["messages"][1]["text"] == "2",
               "/api/threads/<id>: the 2 messages", raw[:200])
            st, _, raw = req(url, "POST", "/api/chat", {"thread": tid, "text": "count", "mode": "ask"}, headers=post, timeout=30)
            evs = sse(raw)
            ok(st == 200 and "".join(d["t"] for e, d in evs if e == "delta") == "4", "a second chat on the thread: the stub saw 4 messages", evs)
            st, _, raw = req(url, "GET", "/api/threads?n=30", headers=bearer)
            ok(json.loads(raw)["threads"][0]["turns"] == 2, "the thread has 2 turns now", raw[:200])
            st, _, _ = req(url, "POST", "/api/chat", {"thread": "2099-01-01-000000", "text": "x"}, headers=post)
            ok(st == 404, "chat on an unknown thread -> 404", st)
            st, _, _ = req(url, "POST", "/api/chat", {"thread": "../etc", "text": "x"}, headers=post)
            ok(st == 400, "chat with a bad thread id -> 400", st)
            st, _, _ = req(url, "GET", "/api/threads/../etc", headers=bearer)
            ok(st == 404, "GET /api/threads/../etc -> 404 (two segments: off the table, no handler sees it)", st)
            st, _, _ = req(url, "GET", "/api/threads/bad.id", headers=bearer)
            ok(st == 400, "GET /api/threads/<bad id> -> 400", st)
            st, _, _ = req(url, "POST", "/api/chat", {"text": "  "}, headers=post)
            ok(st == 400, "chat with empty text -> 400", st)
            st, _, _ = req(url, "POST", "/api/chat", {"text": "x", "mode": "do"}, headers=post)
            ok(st == 400, "chat mode do -> 400", st)
            st, _, raw = req(url, "POST", "/api/chat", {"thread": tid, "text": "count", "mode": "chat"}, headers=post, timeout=30)
            ok(st == 200 and any(e == "done" for e, _d in sse(raw)), "mode chat works", st)
            st, _, raw = req(url, "POST", "/api/chat", {"thread": tid, "text": "count", "mode": "talk"}, headers=post, timeout=30)
            ok(st == 200 and any(e == "done" for e, _d in sse(raw)), "mode talk still accepted (the old name of chat)", st)

            # the stop button: a client that hangs up mid-stream still
            # lands the turn -- the user line and the partial (partial=True)
            u2 = urllib.parse.urlsplit(url)
            c2 = http.client.HTTPConnection(u2.hostname, u2.port, timeout=10)
            c2.request("POST", "/api/chat", json.dumps({"text": "dripfeed"}).encode(),
                       dict(post, **{"Content-Type": "application/json"}))
            r2 = c2.getresponse()
            buf, t_end = b"", time.time() + 10
            while b"event: delta" not in buf and time.time() < t_end:
                chunk = r2.read1(512)
                if not chunk:
                    break
                buf += chunk
            # stop: the socket just goes away (RST, like a browser abort);
            # the OS socket sits under the response once the SSE detaches
            r2.fp.raw._sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            r2.close()
            c2.close()
            got, t_end = None, time.time() + 10
            while got is None and time.time() < t_end:
                time.sleep(0.2)
                st, _, raw = req(url, "GET", "/api/threads?n=10", headers=bearer)
                for t in json.loads(raw).get("threads", []):
                    st2, _, raw2 = req(url, "GET", "/api/threads/" + t["id"], headers=bearer)
                    ms2 = json.loads(raw2).get("messages", [])
                    if (any(m["role"] == "user" and m["text"] == "dripfeed" for m in ms2)
                            and ms2[-1]["role"] == "assistant"):
                        got = ms2
                        break
            ok(got is not None and got[-1]["role"] == "assistant" and got[-1].get("partial") is True
               and got[-1]["text"] and set(got[-1]["text"]) == {"a"},
               "a hung-up chat records the user line and the partial reply, partial=True", got)

            # a client that hangs up WHILE QUEUED pays no prefill and
            # lands no thread: A holds the model with a dripfeed, B gets
            # `queued` and vanishes -- the server logs 499, nothing lands
            st, _, raw = req(url, "GET", "/api/threads?n=50", headers=bearer)
            n_before = len(json.loads(raw)["threads"])
            a_done = []

            def _chat_a():
                a_done.append(req(url, "POST", "/api/chat", {"text": "dripfeed"}, headers=post, timeout=30))
            ta = threading.Thread(target=_chat_a)
            ta.start()
            time.sleep(0.4)                    # A holds the chat lock now
            cb = http.client.HTTPConnection(u2.hostname, u2.port, timeout=10)
            cb.request("POST", "/api/chat", json.dumps({"text": "leftbehind"}).encode(),
                       dict(post, **{"Content-Type": "application/json"}))
            rb = cb.getresponse()
            bufb, t_end = b"", time.time() + 10
            while b"event: queued" not in bufb and time.time() < t_end:
                ch = rb.read1(256)
                if not ch:
                    break
                bufb += ch
            rb.fp.raw._sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            rb.close()
            cb.close()
            ta.join(timeout=30)
            time.sleep(0.5)
            st, _, raw = req(url, "GET", "/api/threads?n=50", headers=bearer)
            th = json.loads(raw)["threads"]
            leftover = []
            for t in th:
                _st2, _, raw2 = req(url, "GET", "/api/threads/" + t["id"], headers=bearer)
                if any(m.get("text") == "leftbehind" for m in json.loads(raw2).get("messages", [])):
                    leftover.append(t["id"])
            ok(b"event: queued" in bufb and not leftover and len(th) == n_before + 1,
               "a client that left while queued lands no thread",
               (bufb[:40], n_before, len(th), leftover))

            # a reply cut mid-stream keeps its thread: the error event
            # carries the id the partial landed on, and the next message
            # continues that same thread
            st, h, raw = req(url, "POST", "/api/chat", {"text": "cutfeed"}, headers=post, timeout=30)
            evs = sse(raw)
            cut_err = next((d for e, d in evs if e == "error"), None)
            ctid = (cut_err or {}).get("thread", "")
            ok(st == 200 and cut_err and cut_err.get("kind") == "cut" and ctid,
               "a cut reply's error event names the thread the partial landed on", evs)
            st, _, raw2 = req(url, "GET", "/api/threads/" + str(ctid), headers=bearer)
            ms3 = json.loads(raw2).get("messages", []) if st == 200 else []
            ok(st == 200 and any(m.get("text") == "cutfeed" for m in ms3)
               and ms3 and ms3[-1].get("partial") is True,
               "the cut thread holds the user line and the partial", (st, ms3))
            st, _, raw3 = req(url, "POST", "/api/chat", {"text": "count", "thread": ctid}, headers=post, timeout=30)
            evs3 = sse(raw3)
            ok(st == 200 and next((d.get("thread") for e, d in evs3 if e == "done"), "") == ctid,
               "the next message continues the same thread", evs3)

            # Timeouts use the same saved-thread contract as disconnects.
            for prompt in ("emptytimeoutfeed", "timeoutfeed"):
                st, _, raw = req(url, "POST", "/api/chat", {"text": prompt}, headers=post, timeout=30)
                evs = sse(raw)
                err = next((d for e, d in evs if e == "error"), {})
                ok(err.get("kind") == "timeout" and not any(e == "done" for e, d in evs),
                   "a timeout emits an error, never a successful done", evs)
                if prompt == "emptytimeoutfeed":
                    ok(not err.get("thread") and not any(e == "delta" for e, d in evs),
                       "a timeout before content lands no turn", evs)
                    continue
                tid = err.get("thread")
                st, _, raw = req(url, "GET", "/api/threads/" + str(tid), headers=bearer)
                rows = json.loads(raw).get("messages", [])
                ok(st == 200 and len(rows) == 2 and rows[-1].get("partial") is True
                   and rows[-1]["text"] == "half an ", "timeout saves one incomplete assistant turn", rows)
                st, _, raw = req(url, "POST", "/api/chat", {"text": "go on", "thread": tid}, headers=post)
                ok(next((d.get("thread") for e, d in sse(raw) if e == "done"), None) == tid
                   and any(m.get("content") == "half an " for m in SEEN["body"]["messages"]),
                   "timeout follow-up reaches the model with the partial on its original thread")

            st, _, raw = req(url, "GET", "/api/soul", headers=bearer)
            d = json.loads(raw)
            ok(st == 200 and d == {"text": "Call yourself Fixture.", "source": "file"}, "/api/soul: the fixture soul", raw[:100])
            st, _, raw = req(url, "POST", "/api/soul", {"text": "New soul."}, headers=post)
            soulf = home + "/.config/spark/soul"
            ok(st == 200 and json.loads(raw) == {"chars": 9, "cut": False, "part": "soul"} and open(soulf).read() == "New soul.\n"
               and oct(os.stat(soulf).st_mode & 0o777) == "0o600", "POST /api/soul writes the file 0600", raw[:100])
            st, _, raw = req(url, "GET", "/api/soul", headers=bearer)
            ok(json.loads(raw)["text"] == "New soul.", "GET /api/soul reflects it", raw[:100])
            SEEN.clear()
            req(url, "POST", "/v1/chat/completions", {"messages": [{"role": "user", "content": "what"}], "stream": False}, headers=bearer)
            sys0 = SEEN.get("body", {}).get("messages", [{}])[0].get("content", "")
            ok("New soul." in sys0 and "Fixture" not in sys0, "the next /v1 request carries the new soul", sys0[:200])
            st, _, _ = req(url, "POST", "/api/soul", {"text": "Call yourself Fixture."}, headers=post)
            ok(st == 200 and open(soulf).read() == "Call yourself Fixture.\n", "and back to the fixture soul")
            rc, out, _ = spark("serve", "--audit", "--porcelain")
            souls = [l.split("\t") for l in out.splitlines() if l.split("\t")[2:3] == ["soul"]]
            ok(rc == 0 and len(souls) == 2 and souls[0][3] == "chars=9 part=soul",
               "POST /api/soul writes an audit record each time: the part and its length, never the text", out[-300:])

            st, _, raw = req(url, "GET", "/api/memory", headers=bearer)
            ok(st == 200 and json.loads(raw) == {"facts": [], "on": True}, "/api/memory: nothing yet, on", raw[:100])
            st, _, raw = req(url, "POST", "/api/memory", {"text": "the box is  called forge"}, headers=post)
            ok(st == 200 and json.loads(raw) == {"n": 1, "text": "the box is called forge"}, "POST /api/memory keeps a fact (spaces folded)", raw[:100])
            rc, out, _ = spark("memory")
            ok(rc == 0 and "1 fact" in out and "1   the box is called forge" in out, "spark memory on the same HOME lists it", out)
            st, _, raw = req(url, "GET", "/api/memory", headers=bearer)
            ok(json.loads(raw)["facts"] == [{"n": 1, "text": "the box is called forge"}], "GET /api/memory lists it numbered", raw[:100])
            st, _, _ = req(url, "POST", "/api/memory", {"text": "The box is called forge"}, headers=post)
            ok(st == 409, "the same fact again -> 409", st)
            st, _, _ = req(url, "POST", "/api/memory", {"text": " "}, headers=post)
            ok(st == 400, "an empty fact -> 400", st)
            st, _, _ = req(url, "POST", "/api/memory", {"text": "x" * 201}, headers=post)
            ok(st == 400, "a 201-char fact -> 400", st)
            SEEN.clear()
            req(url, "POST", "/v1/chat/completions", {"messages": [{"role": "user", "content": "what"}], "stream": False}, headers=bearer)
            sys0 = SEEN.get("body", {}).get("messages", [{}])[0].get("content", "")
            ok("- the box is called forge" in sys0, "the fact rides in the identity", sys0[:300])
            SEEN.clear()
            req(url, "POST", "/v1/chat/completions",
                {"identity": False, "messages": [{"role": "system", "content": "OWN-PERSONA"}, {"role": "user", "content": "what"}], "stream": False}, headers=bearer)
            sb = json.dumps(SEEN.get("body", {}))
            ok("OWN-PERSONA" in sb and "the box is called forge" not in sb and "Fixture" not in sb,
               "identity false: neither the fact nor the soul rides", sb[:300])
            st, _, _ = req(url, "DELETE", "/api/memory/1", headers=bearer)
            ok(st == 403, "DELETE without X-Spark -> 403", st)
            st, _, _ = req(url, "DELETE", "/api/memory/9", headers=post)
            ok(st == 404, "DELETE a fact that is not there -> 404", st)
            st, _, raw = req(url, "DELETE", "/api/memory/1", headers=post)
            ok(st == 200 and json.loads(raw) == {"text": "the box is called forge"}, "DELETE /api/memory/1", raw[:100])
            st, _, raw = req(url, "GET", "/api/memory", headers=bearer)
            ok(json.loads(raw)["facts"] == [], "GET /api/memory: empty again", raw[:100])
            rc, out, _ = spark("memory")
            ok(rc == 0 and "0 facts" in out, "spark memory agrees", out)

            st, _, raw = req(url, "POST", "/api/do/propose", {"text": "say hello"}, headers=post, timeout=30)
            d = json.loads(raw)
            ok(st == 200 and d.get("thread") and d["reply"] == {"kind": "cmd", "command": "echo STEP-ONE",
                                                                "hint": "say hello", "danger": False, "proof": ""}
               and isinstance(d.get("ms"), int), "/api/do/propose: the step, a thread, nothing run", raw[:300])
            dtid = d.get("thread", "")
            first_sent = SEEN["body"]["messages"]
            dturns = [json.loads(l) for f in sorted(os.listdir(state + "/turns")) for l in open(state + "/turns/" + f)
                      if l.strip() and json.loads(l).get("mode") == "do"]
            dturn = dturns[-1] if dturns else {}
            ok(dturn.get("kind") == "cmd" and dturn.get("pp_n") == 40 and dturn.get("cache_n") == 30
               and dturn.get("model") == hj["roles"]["ember"] and dturn.get("thread") == dtid,
               "/api/do/propose records its turn: mode do, pp_n/cache_n, the ember's stem", dturns)
            st, _, raw = req(url, "POST", "/api/do/run", {"command": "echo hi"}, headers=post)
            ok(st == 200 and json.loads(raw) == {"rc": 0, "tail": "hi\n"}, "/api/do/run echo hi -> rc 0, tail", raw[:100])
            st, _, raw = req(url, "POST", "/api/do/run", {"command": "echo do-run-marker-words"}, headers=post)
            lg = [l for l in open(state + "/forge.log").read().splitlines() if " do/run " in l]
            digest = hashlib.sha256(b"echo do-run-marker-words").hexdigest()[:12]
            ok(st == 200 and any(l.endswith(" do/run %s 24 chars" % digest) for l in lg)
               and any(l.endswith(" do/run %s rc 0" % digest) for l in lg)
               and not any("marker" in l or "echo" in l for l in lg),
               "forge.log keeps a do/run's digest and length, never its text", lg[-4:])
            st, _, raw = req(url, "POST", "/api/do/run", {"command": "false"}, headers=post)
            ok(st == 200 and json.loads(raw)["rc"] == 1, "/api/do/run false -> rc 1 (run as clicked, not re-judged)", raw[:100])
            st, _, raw = req(url, "POST", "/api/do/run", {"command": "fakeflag --frob"}, headers=post)
            d = json.loads(raw) if st == 200 else {}
            ok(st == 200 and d.get("rc") == 2 and "unrecognized option" in d.get("tail", "")
               and d.get("man") == "From man fakeflag:\nOPTIONS\n     --frob  never an option here",
               "/api/do/run of a step refused for an option -> {rc, tail, man}: its man page's lines", raw[:300])
            st, _, raw = req(url, "POST", "/api/do/run", {"command": "pwd", "cwd": tmp}, headers=post)
            ok(st == 200 and json.loads(raw)["tail"].strip().endswith(os.path.basename(tmp)), "/api/do/run honours cwd", raw[:100])
            # the cwd of a do route: one line, absolute, a directory -- else 400
            for route, extra in (("/api/do/run", {"command": "pwd"}), ("/api/do/propose", {"text": "say hello"})):
                for bad in ("relative/dir", os.path.join(tmp, "no-such-dir"), tmp + "\x1b[2K", tmp + "\u202e"):
                    st, _, raw = req(url, "POST", route, dict(extra, cwd=bad), headers=post, timeout=30)
                    err = json.loads(raw).get("error", {}) if st == 400 else {}
                    ok(st == 400 and err.get("kind") == "bad" and "cwd" in err.get("hint", ""),
                       "%s with cwd %r -> 400 {error: {kind: bad}}" % (route, bad[-14:]), (st, raw[:120]))
            # a new thread's goal: do.DO_GOAL_MAX at most
            st, _, raw = req(url, "POST", "/api/do/propose", {"text": "x" * 9000}, headers=post, timeout=30)
            err = json.loads(raw).get("error", {}) if st == 400 else {}
            ok(st == 400 and err.get("kind") == "bad" and err.get("hint") == "a goal is at most 8 kB -- this one is 9 kB",
               "/api/do/propose: a goal over 8 kB -> 400, the house error shape", (st, raw[:120]))
            st, _, _ = req(url, "POST", "/api/do/run", {"command": ""}, headers=post)
            ok(st == 400, "/api/do/run with no command -> 400", st)
            # v1.70: a block -- lines a line feed separates -- runs whole;
            # any other control character in it is still refused
            st, _, raw = req(url, "POST", "/api/do/run", {"command": "echo one\necho two", "cwd": tmp}, headers=post)
            ok(st == 200 and json.loads(raw) == {"rc": 0, "tail": "one\ntwo\n"},
               "/api/do/run of a block (two lines) runs both lines", (st, raw[:80]))
            for bad, what in (("echo one\recho two\necho three", "a CR"), ("echo one\n\techo two", "a TAB"),
                              ("echo one\necho \x1b[2K two", "an escape"), ("echo one\necho \u202e two", "a bidi mark")):
                st, _, raw = req(url, "POST", "/api/do/run", {"command": bad, "cwd": tmp}, headers=post)
                ok(st == 400 and json.loads(raw).get("error", {}).get("kind") == "bad",
                   "/api/do/run of a block carrying %s -> 400" % what, (st, raw[:80]))
            st, _, raw = req(url, "POST", "/api/do/run", {"command": "echo one\n" + "x" * 16400}, headers=post)
            ok(st == 400 and json.loads(raw).get("error", {}).get("hint") == "a block is at most 16384 characters",
               "/api/do/run of a block over 16 kB -> 400, before any pattern", (st, raw[:120]))
            st, _, raw = req(url, "POST", "/api/do/run",
                             {"command": "cat > blk.txt <<'EOF'\na\n" + "y" * 6000 + "\nEOF", "cwd": tmp}, headers=post)
            ok(st == 200 and json.loads(raw)["rc"] == 0
               and open(os.path.join(tmp, "blk.txt")).read() == "a\n" + "y" * 6000 + "\n",
               "/api/do/run of a block past a line's 4096 characters runs (one here-document, a new file: no danger)",
               (st, raw[:80]))
            os.remove(os.path.join(tmp, "blk.txt"))
            st, _, raw = req(url, "POST", "/api/do/run",
                             {"command": "printf 'a\\n' > blk.txt\necho done", "cwd": tmp}, headers=post)
            ok(st == 400 and json.loads(raw).get("error", {}).get("kind") == "confirm"
               and not os.path.exists(os.path.join(tmp, "blk.txt")),
               "/api/do/run of a redirect, then another line -> 400 confirm (only a lone here-document is read past)",
               (st, raw[:80]))
            st, _, raw = req(url, "POST", "/api/do/run", {"command": "printf 'a\\n' > blk.txt", "cwd": tmp,
                                                          "confirmed": True}, headers=post)
            ok(st == 200 and open(os.path.join(tmp, "blk.txt")).read() == "a\n",
               "/api/do/run of a one-line redirect runs with confirmed: true (v1.69's verdict)", (st, raw[:80]))
            # one line plus a trailing newline is a line: its 4096 cap, not a block's 16 kB
            st, _, raw = req(url, "POST", "/api/do/run", {"command": "echo hey\n", "cwd": tmp}, headers=post)
            ok(st == 200 and json.loads(raw) == {"rc": 0, "tail": "hey\n"},
               "/api/do/run of one line and a trailing newline runs as that line", (st, raw[:80]))
            st, _, raw = req(url, "POST", "/api/do/run", {"command": "echo " + "z" * 5000 + "\n\n"}, headers=post)
            ok(st == 400 and json.loads(raw).get("error", {}).get("hint")
               == "a command is at most %d characters" % _fsv.DO_COMMAND_MAX,
               "/api/do/run of a 5000-character line and a trailing newline -> 400, a line's cap (never a block's)",
               (st, raw[:120]))
            st, _, raw = req(url, "POST", "/api/do/run", {"command": "echo one\necho b > blk.txt", "cwd": tmp}, headers=post)
            ok(st == 400 and json.loads(raw).get("error", {}).get("kind") == "confirm",
               "/api/do/run of a block that overwrites a file that is there -> 400 confirm", (st, raw[:80]))
            st, _, raw = req(url, "POST", "/api/do/propose", {"text": "blockstep", "cwd": tmp}, headers=post, timeout=30)
            d = json.loads(raw) if st == 200 else {}
            ok(st == 200 and d.get("reply") == {"kind": "cmd", "command": smoke.BLOCK_STEP, "hint": "write the script",
                                                "danger": False, "proof": ""},
               "/api/do/propose returns a block as it is: its lines, no danger for a new file", raw[:300])
            # v1.56: the length is capped before any pattern reads the
            # command -- a 100 kB line once pinned a thread in is_dangerous
            from spark import forgeserve as _fsv_cap
            t0 = time.time()
            st, _, raw = req(url, "POST", "/api/do/run", {"command": "echo " + "-u " * 30000}, headers=post)
            err = json.loads(raw).get("error", {}) if st == 400 else {}
            ok(st == 400 and err.get("hint") == "a command is at most %d characters" % _fsv_cap.DO_COMMAND_MAX
               and time.time() - t0 < 2,
               "/api/do/run of a command over 4096 characters -> 400 at once, before any pattern", (st, raw[:120]))
            st, _, raw = req(url, "POST", "/api/do/run", {"command": "echo " + "x" * (_fsv_cap.DO_COMMAND_MAX - 5)}, headers=post)
            ok(st == 200 and json.loads(raw)["rc"] == 0, "/api/do/run of a command of exactly 4096 characters still runs", (st, raw[:80]))
            gone =os.path.join(tmp, "gone")
            st, _, raw = req(url, "POST", "/api/do/run", {"command": "rm -rf " + gone}, headers=post)
            kind = json.loads(raw).get("error", {}).get("kind") if st == 400 else ""
            ok(st == 400 and kind == "confirm", "/api/do/run of a dangerous command without confirmed -> 400 confirm", (st, raw[:80]))
            st, _, _ = req(url, "POST", "/api/do/run", {"command": "rm -rf " + gone, "confirmed": "yes"}, headers=post)
            ok(st == 400, "confirmed must be true, not a word", st)
            st, _, raw = req(url, "POST", "/api/do/run", {"command": "rm -rf " + gone, "confirmed": True}, headers=post)
            ok(st == 200 and json.loads(raw)["rc"] == 0, "with confirmed: true the dangerous command runs", raw[:80])
            st, _, raw = req(url, "POST", "/api/do/propose", {"thread": dtid, "text": "Output of `echo STEP-ONE` (exit 0):\nSTEP-ONE"}, headers=post, timeout=30)
            d = json.loads(raw)
            ok(st == 200 and d["thread"] == dtid and d["reply"]["kind"] == "done", "/api/do/propose on the thread: done", raw[:200])
            replay = SEEN["body"]["messages"]
            ok(replay[1]["content"].startswith("[cwd ") and replay[1] == first_sent[1] and replay[0] == first_sent[0]
               and replay[2] == {"role": "assistant", "content": "`echo STEP-ONE` -- say hello"},
               "a replayed page do thread: the goal as it was sent, [cwd] line and all -- the prefix the cache holds",
               (replay[1]["content"][:60], first_sent[1]["content"][:60]))
            ok(d.get("driver") == hj["roles"]["ember"] and d.get("unchecked") == [],
               "/api/do/propose done: driver is the ember's stem, unchecked empty", (d.get("driver"), d.get("unchecked")))
            st, _, raw = req(url, "GET", "/api/threads/" + dtid, headers=bearer)
            ok(st == 200 and len(json.loads(raw)["messages"]) == 4, "the do thread holds goal / step / output / done", raw[:300])
            st, _, raw = req(url, "POST", "/api/do/propose", {"text": "badsum count"}, headers=post, timeout=30)
            d = json.loads(raw)
            btid = d.get("thread", "")
            ok(st == 200 and d["reply"]["command"] == "echo 21; echo 5" and d.get("unchecked") == [],
               "/api/do/propose badsum: the counting step; a cmd is never flagged", raw[:300])
            st, _, raw = req(url, "POST", "/api/do/propose", {"thread": btid, "text": "Output of `echo 21; echo 5` (exit 0):\n21\n5"}, headers=post, timeout=30)
            d = json.loads(raw)
            ok(st == 200 and d["reply"]["kind"] == "done" and d.get("unchecked") == ["96"],
               "/api/do/propose: a done number no output backs comes back unchecked", raw[:300])
            lg = open(state + "/forge.log").read()
            ok(re.search(r"do/run [0-9a-f]{12} 7 chars$", lg, re.M) and re.search(r"do/run [0-9a-f]{12} 5 chars$", lg, re.M)
               and re.search(r"do/run [0-9a-f]{12} rc 1$", lg, re.M)
               and not re.search(r"do/run [0-9a-f]{12} (echo hi|false)$", lg, re.M),
               "forge.log names the commands run by a sha256 prefix and a length, never the text; the rc after",
               lg[-300:])
            # the audit trail: one sealed record per admin action in the box
            # account's store, numbers and names only, never the command
            import base64 as _b64
            import hashlib as _hl
            from spark import vault as _vault
            adk = _b64.b64decode(open(state + "/account-key").read().split()[-1])

            def audit_recs():
                return [json.loads(r) for r in _vault.read_sealed(state + "/users/owner/audit", adk, "audit", "owner")]
            arecs = audit_recs()
            runs = [r for r in arecs if r.get("action") == "do/run"]
            hi = [r for r in runs if r.get("digest") == _hl.sha256(b"echo hi").hexdigest()[:12]]
            ok(len(hi) == 1 and set(hi[0]) == {"ts", "ip", "action", "digest", "rc"} and hi[0]["rc"] == 0
               and hi[0]["ip"] == "127.0.0.1", "do/run echo hi landed one audit record: {ts, ip, action, digest, rc}", hi)
            # 11: the marker run, the 4096-character run, the two blocks,
            # the confirmed one-line redirect and the line with its trailing
            # newline count; the refused 90 kB one and the refused blocks do not
            ok(len(runs) == 11 and all(isinstance(r["rc"], int) and re.match(r"^[0-9a-f]{12}$", r["digest"]) for r in runs),
               "every do/run that ran (11) has its record: rc a number, digest 12 hex", runs)
            blob = json.dumps(arecs)
            ok("echo hi" not in blob and "rm -rf" not in blob and "pwd" not in blob and tmp not in blob,
               "no command text, no path in the trail", blob[:200])
            ok(oct(os.stat(state + "/users/owner/audit").st_mode & 0o777) == "0o600", "the trail is 0600")
            # nobody watches a page step at a terminal: do.STEP_TIMEOUT is its leash
            t0 = time.time()
            st, _, raw = req(url, "POST", "/api/do/run", {"command": "echo started; sleep 30"}, headers=post, timeout=30)
            took = time.time() - t0
            d = json.loads(raw) if st == 200 else {}
            ok(d.get("rc") == 124 and "started" in d.get("tail", "") and STEP_TIMEOUT <= took < STEP_TIMEOUT + 8,
               "/api/do/run of a hanging step: rc 124 at do.STEP_TIMEOUT, the tail so far", (st, raw[:100], round(took, 1)))
            # a continued page thread's text is a step's output: held before the model sees it
            gh = "ghp_Z9y8X7w6V5u4T3s2R1q0P9o8N7m6L5k4J3i2"  # spark:allow-secret
            st, _, raw = req(url, "POST", "/api/do/propose",
                             {"thread": dtid, "text": "Output of `cat creds` (exit 0):\ndeploy token " + gh}, headers=post, timeout=30)
            sent = json.dumps(SEEN["body"])
            dturns = [json.loads(l) for f in sorted(os.listdir(state + "/turns")) for l in open(state + "/turns/" + f)
                      if l.strip() and json.loads(l).get("mode") == "do"]
            ok(st == 200 and gh not in sent and "deploy token [held]" in sent and dturns and dturns[-1].get("held") == 1,
               "/api/do/propose on a thread: a secret in the step's output is held; held=1 on the turn", sent[-200:])

            st, h, raw = req(url, "POST", "/api/run", {"verb": "model", "args": ["none"]}, headers=post, timeout=60)
            evs = sse(raw)
            lines = [d["s"] for e, d in evs if e == "line"]
            ok(st == 200 and any(l.startswith("ok     site") and "SITE_AI_MODEL=none" in l for l in lines) and ("done", {"rc": 0}) in evs,
               "/api/run model none: streams the verb's lines, done rc 0", evs)
            last = audit_recs()[-1]
            ok(set(last) == {"ts", "ip", "action", "verb", "rc"} and last["action"] == "run" and last["verb"] == "model"
               and last["rc"] == 0 and last["ip"] == "127.0.0.1",
               "/api/run model none landed one audit record: {ts, ip, action, verb, rc}", last)
            ok("none" not in json.dumps(last), "the run record carries the verb, not its arguments", last)
            rc, out, _ = spark("forge", "audit", "--porcelain")
            cols = out.rstrip("\n").split("\n")[-1].split("\t")
            ok(rc == 0 and len(cols) == 4 and cols[1] == "127.0.0.1" and cols[2] == "run" and cols[3] == "rc=0 verb=model",
               "spark forge audit --porcelain: four tab-separated columns, the newest last", out[-200:])
            rc, out, _ = spark("forge", "audit", "2")
            ok(rc == 0 and len(out.splitlines()) == 2 and "echo hi" not in out and "do/run" in out and "run" in out,
               "spark forge audit 2 (the older spelling): two lines, no command text", out)
            rc, out2, _ = spark("serve", "--audit", "2")
            ok(rc == 0 and out2 == out, "spark serve --audit 2: the same two lines", out2)
            ok(any(r.get("action") == "user add" and r.get("name") == "ualice" and r.get("ip") == "cli"
                   and set(r) == {"ts", "ip", "action", "name"} for r in audit_recs()),
               "spark user add landed {ts, ip: cli, action, name}")
            rc, out, _ = spark("serve", "--audit", "x")
            ok(rc == 2 and out.startswith("spark serve -- --audit takes a count"), "spark serve --audit x: signed, exit 2", out)
            ok("SITE_AI_MODEL=none" in open(home + "/.config/spark/site.env").read(), "site.env has SITE_AI_MODEL=none (SPARK_NO_APPLY)")
            st, h, raw = req(url, "POST", "/api/run", {"verb": "ember", "args": ["none"]}, headers=post, timeout=60)
            evs = sse(raw)
            lines = [d["s"] for e, d in evs if e == "line"]
            ok(st == 200 and any(l.startswith("ok     site") and "SITE_EMBER_MODEL=none" in l for l in lines) and ("done", {"rc": 0}) in evs,
               "/api/run ember none: streams the verb's lines, done rc 0", evs)
            ok("SITE_EMBER_MODEL=none" in open(home + "/.config/spark/site.env").read(), "site.env has SITE_EMBER_MODEL=none (SPARK_NO_APPLY)")
            st, _, raw = req(url, "DELETE", "/api/threads", headers=post)
            ok(st == 200 and not __import__("glob").glob(state + "/users/owner/threads/*"),
               "DELETE /api/threads empties the requester's own store", raw[:100])
            st, _, _ = req(url, "POST", "/api/run", {"verb": "check", "args": []}, headers=post)
            ok(st == 400, "/api/run check -> 400", st)
            for gone in ("theme", "font", "quiet"):
                st, _, _ = req(url, "POST", "/api/run", {"verb": gone, "args": ["none"]}, headers=post)
                ok(st == 400, "/api/run %s is no verb the page may run (v1.62) -> 400" % gone, st)
            for args in (["off"], ["off", "--force"], ["boot", "on"], ["share", "on"], ["on"], ["--login", "--show-token"]):
                st, _, _ = req(url, "POST", "/api/run", {"verb": "serve", "args": args}, headers=post)
                ok(st == 400, "/api/run serve %s: the page never switches the server -> 400" % " ".join(args), st)
            st, _, _ = req(url, "POST", "/api/run", {"verb": "history", "args": ["clear"]}, headers=post)
            ok(st == 400, "/api/run history is gone (DELETE /api/threads instead) -> 400", st)
            st, _, _ = req(url, "POST", "/api/run", {"verb": "model", "args": ["none; rm -rf /"]}, headers=post)
            ok(st == 400, "/api/run with a ; in an arg -> 400", st)
            st, _, _ = req(url, "POST", "/api/run", {"verb": "model", "args": "none"}, headers=post)
            ok(st == 400, "/api/run args not a list -> 400", st)
            st, _, _ = req(url, "POST", "/api/run", {"verb": "model", "args": ["none"]}, headers=bearer)
            ok(st == 403, "/api/run without X-Spark -> 403", st)
            st, _, _ = req(url, "POST", "/api/chat", {"text": "x"}, headers=bearer)
            ok(st == 403, "/api/chat without X-Spark -> 403", st)
            st, _, _ = req(url, "GET", "/api/threads", headers={})
            ok(st == 401, "/api/threads bare -> 401", st)

            # the user role: a personal token
            st, h, raw = login(utoken)
            usc = h.get("Set-Cookie", "")
            ok(st == 200 and usc.startswith("spark_forge=") and json.loads(raw).get("role") == "user"
               and json.loads(raw).get("user") == "ualice",
               "user login (personal token) -> cookie, role user, the name", (st, raw[:100]))
            ok(usc.split(";")[0] != sc.split(";")[0], "the user cookie differs from the admin cookie")
            ucookie = {"Cookie": usc.split(";")[0]}
            st, _, raw = req(url, "GET", "/api/me", headers=ucookie)
            ok(st == 200 and json.loads(raw).get("role") == "user", "/api/me with the user cookie: role user", raw[:100])
            st, _, raw = req(url, "GET", "/api/me", headers=ubearer)
            ok(st == 200 and json.loads(raw).get("role") == "user", "/api/me with the user bearer: role user", raw[:100])
            # logout revokes the SESSION, not only the cookie: the same
            # cookie replayed afterwards is 401
            st, _, _ = req(url, "POST", "/api/logout", {}, headers=dict(ucookie, **{"X-Spark": "1", "Origin": url}))
            ok(st == 200, "the user logs out", st)
            st, _, _ = req(url, "GET", "/api/me", headers=ucookie)
            ok(st == 401, "the logged-out cookie replayed -> 401 (the session died with it)", st)
            st, h, raw = login(utoken)
            usc = h.get("Set-Cookie", "")
            ucookie = {"Cookie": usc.split(";")[0]}
            st, _, raw = req(url, "GET", "/api/me", headers=ucookie)
            ok(st == 200 and json.loads(raw).get("role") == "user", "a fresh login mints a working session again", raw[:100])
            upost = dict(ubearer, **{"X-Spark": "1", "Origin": url})
            st, h, raw = req(url, "POST", "/api/chat", {"text": "count"}, headers=upost, timeout=30)
            evs = sse(raw)
            ok(st == 200 and h.get("Content-Type", "").startswith("text/event-stream")
               and "".join(d["t"] for e, d in evs if e == "delta") == "2" and any(e == "done" for e, d in evs),
               "a user chats: the SSE streams and finishes", evs)
            atid = next((d.get("thread") for e, d in evs if e == "done"), "")
            apath = state + "/users/ualice/threads/" + str(atid) + ".sealed"
            ok(atid and os.path.isfile(apath) and open(apath, "rb").read(23) == b"spark-sealed-v1 thread ",
               "alice's thread lands sealed under users/ualice", apath)
            st, _, raw = req(url, "GET", "/api/threads", headers=ubearer)
            ok(st == 200 and any(t["id"] == atid for t in json.loads(raw)["threads"]), "alice lists her thread", raw[:150])
            # prune reaches every store the server holds a key for --
            # alice's key is cached from her login -- and a header-only
            # file from a failed first turn goes after a day, key or not
            # (35 days old prunes under the default SPARK_HISTORY too)
            import shutil as _sh
            oldp = state + "/users/ualice/threads/2020-01-01-000001.sealed"
            hdrp = state + "/users/ualice/threads/2020-01-01-000002.sealed"
            _sh.copyfile(apath, oldp)
            with open(hdrp, "w") as f:
                f.write("spark-sealed-v1 thread 2020-01-01-000002\n")
            oldt = time.time() - 35 * 86400
            os.utime(oldp, (oldt, oldt))
            hdt = time.time() - 2 * 86400
            os.utime(hdrp, (hdt, hdt))
            st, _, _ = req(url, "POST", "/api/chat", {"text": "count"},
                           headers=dict(ubearer, **{"X-Spark": "1", "Origin": url}), timeout=30)
            t_end = time.time() + 5
            while (os.path.exists(oldp) or os.path.exists(hdrp)) and time.time() < t_end:
                time.sleep(0.2)
            ok(not os.path.exists(oldp) and not os.path.exists(hdrp),
               "prune reaches alice's store and drops her stale header-only file",
               (os.path.exists(oldp), os.path.exists(hdrp)))

            # one identity, every door: `??` on a CLIENT continues the
            # newest thread on the FORGE for the logged-in user, and the
            # turn lands THERE -- the box's prompt, the client's prompt
            # and the page share one thread
            chome = tempfile.mkdtemp(prefix="spark-client-")
            cenv = {k: v for k, v in env.items() if not k.startswith(("XDG_", "SITE_", "SPARK_BASE_URL"))}
            cenv.update({"HOME": chome, "XDG_CONFIG_HOME": chome + "/.config",
                         "XDG_STATE_HOME": chome + "/.local/state", "XDG_DATA_HOME": chome + "/.local/share",
                         "SITE_AI_MODEL": "none", "SITE_PEER_AI_URL": url, "SPARK_NO_REFRESH": "1"})
            os.makedirs(chome + "/.local/state/spark", mode=0o700)
            with open(chome + "/.local/state/spark/account", "w") as f:
                f.write("name=ualice\ntoken=%s\n" % utoken)
            os.chmod(chome + "/.local/state/spark/account", 0o600)
            st, _, raw = req(url, "GET", "/api/threads?n=1", headers=ubearer)
            ntid = json.loads(raw)["threads"][0]["id"]
            st, _, raw = req(url, "GET", "/api/threads/" + str(ntid), headers=ubearer)
            n_msgs = len(json.loads(raw)["messages"])
            p3 = subprocess.run([sys.executable, SPARK, "line", "--cwd", chome, "--shell", "zsh"],
                                input="?? count", capture_output=True, text=True, env=cenv, timeout=30)
            ok(p3.returncode == 0 and p3.stdout.startswith("answer"),
               "a client's ?? answers through the peer", p3.stdout[:80] + p3.stderr[:120])
            st, _, raw = req(url, "GET", "/api/threads/" + str(ntid), headers=ubearer)
            ms4 = json.loads(raw)["messages"]
            ok(len(ms4) == n_msgs + 2 and ms4[-2]["text"] == "count" and ms4[-2].get("mode") == "line"
               and ms4[-1]["role"] == "assistant",
               "the client's turn landed on the FORGE thread (user line + answer)",
               (n_msgs, len(ms4), ms4[-2:]))
            cthreads = []
            cudir = chome + "/.local/state/spark/users"
            for _r, _d, fs in os.walk(cudir):
                cthreads += [f for f in fs if f.endswith(".sealed")]
            ok(not cthreads, "no thread landed in the client's own store", cthreads)
            import shutil as _sh2
            _sh2.rmtree(chome, ignore_errors=True)

            bbearer = {"Authorization": "Bearer " + btoken}
            st, _, raw = req(url, "GET", "/api/threads", headers=bbearer)
            ok(st == 200 and json.loads(raw)["threads"] == [], "bob's thread list is empty", raw[:100])
            st, _, _ = req(url, "GET", "/api/threads/" + str(atid), headers=bbearer)
            ok(st == 404, "bob cannot read alice's thread", st)
            st, _, raw = req(url, "GET", "/api/threads", headers=bearer)
            ok(st == 200 and not any(t["id"] == atid for t in json.loads(raw)["threads"]),
               "the admin's list is the box account's, never alice's", raw[:150])
            st, _, raw = req(url, "GET", "/api/users", headers=bearer)
            du = json.loads(raw)
            ok(st == 200 and any(u["name"] == "ualice" and u["threads"] >= 1 for u in du["users"]),
               "/api/users: names, counts and stamps", raw[:200])
            ok(len(du["users"]) >= 3 and all(set(u) == {"name", "threads", "kept", "last", "account"} for u in du["users"])
               and sum(1 for u in du["users"] if u["account"]) <= 1,
               "every /api/users entry carries exactly {name, threads, kept, last, account}, one account at most", raw[:200])
            st, _, _ = req(url, "GET", "/api/users", headers=ubearer)
            ok(st == 403, "a user cannot list the users", st)

            # a user minted from the page: the admin's POST /api/users, the
            # token once with its login link and the link's QR as a matrix
            from spark import qr as _qr
            xs = {"X-Spark": "1"}
            st, _, raw = req(url, "POST", "/api/users", {"name": "upage"}, headers=dict(bearer, **xs))
            dn = json.loads(raw) if st == 200 else {}
            ok(st == 200 and set(dn) == {"name", "token", "link", "qr"} and dn["name"] == "upage"
               and len(dn["token"]) >= 40 and dn["link"].endswith("#t=" + dn["token"]),
               "POST /api/users: a user minted, the token and its link once", raw[:120] if st != 200 else "")
            nq = len(dn.get("qr") or [])
            ok(nq >= 21 and all(len(r) == nq and set(r) <= {0, 1} for r in dn["qr"]) and dn["qr"] == _qr.encode(dn["link"]),
               "POST /api/users: the QR is qr.encode of the login link, a square 0/1 matrix", nq)
            st, _, raw = req(url, "GET", "/api/me", headers={"Authorization": "Bearer " + dn.get("token", "x")})
            ok(st == 200 and json.loads(raw).get("user") == "upage", "the minted token opens /api/me as that user", raw[:100])
            st, _, _ = req(url, "POST", "/api/users", {"name": "upage"}, headers=dict(bearer, **xs))
            ok(st == 409, "POST /api/users: a name in use is 409", st)
            st, _, _ = req(url, "POST", "/api/users", {"name": "Bad Name"}, headers=dict(bearer, **xs))
            ok(st == 400, "POST /api/users: a name the verb refuses is 400", st)
            st, _, _ = req(url, "POST", "/api/users", {"name": "uother"}, headers=dict(ubearer, **xs))
            ok(st == 403, "a user cannot mint a user", st)
            st, _, raw = req(url, "GET", "/api/users", headers=bearer)
            ok(st == 200 and any(u["name"] == "upage" for u in json.loads(raw)["users"]), "the minted user is listed", raw[:120])
            # /api/me: the newest release the checkout knows, for the admin alone
            st, _, raw = req(url, "GET", "/api/me", headers=bearer)
            dme = json.loads(raw)
            ok(st == 200 and isinstance(dme.get("newest"), str) and (dme["newest"] == "" or re.match(r"^\d+\.\d+(\.\d+)?$", dme["newest"])),
               "/api/me (admin) carries newest, the newest v* tag as X.Y or X.Y.Z", raw[:160])
            st, _, raw = req(url, "GET", "/api/me", headers=ubearer)
            ok(st == 200 and "newest" not in json.loads(raw), "/api/me (a user) carries no newest", raw[:160])
            # removed from the page: the store gone, the token dead, the row gone
            ptoken = dn.get("token", "x")
            st, _, _ = req(url, "DELETE", "/api/users/upage", headers=dict(ubearer, **xs))
            ok(st == 403, "a user cannot remove a user (403)", st)
            st, _, _ = req(url, "DELETE", "/api/users/Upage", headers=dict(bearer, **xs))
            ok(st == 400, "DELETE /api/users/NAME: a name the verb refuses is 400", st)
            st, _, _ = req(url, "DELETE", "/api/users/unobody", headers=dict(bearer, **xs))
            ok(st == 404, "DELETE /api/users/NAME: an unknown name is 404", st)
            st, _, _ = req(url, "DELETE", "/api/users/upage", headers=bearer)
            ok(st == 403, "DELETE /api/users/NAME goes through the write gate: no X-Spark is 403", st)
            st, _, raw = req(url, "DELETE", "/api/users/upage", headers=dict(bearer, **xs))
            ok(st == 200 and json.loads(raw) == {"name": "upage", "removed": True} and not os.path.isdir(state + "/users/upage"),
               "DELETE /api/users/upage: 200, the store gone", raw[:120])
            st, _, _ = req(url, "GET", "/api/me", headers={"Authorization": "Bearer " + ptoken})
            ok(st == 401, "the removed user's token is dead", st)
            st, _, _ = req(url, "DELETE", "/api/users/upage", headers=dict(bearer, **xs))
            ok(st == 404, "removed twice is 404", st)
            st, _, raw = req(url, "GET", "/api/users", headers=bearer)
            ok(st == 200 and not any(u["name"] == "upage" for u in json.loads(raw)["users"]), "the removed user is not listed", raw[:120])
            acct = ""
            try:
                with open(state + "/account", encoding="utf-8") as f:
                    acct = next((ln.split("=", 1)[1].strip() for ln in f if ln.startswith("name=")), "")
            except OSError:
                pass
            if acct:
                st, _, raw = req(url, "DELETE", "/api/users/" + acct, headers=dict(bearer, **xs))
                ok(st == 409 and json.loads(raw)["error"]["kind"] == "self" and os.path.isdir(state + "/users/" + acct),
                   "DELETE of the box account is 409 self, and the store stays", (st, raw[:120]))
            else:
                ok(True, "(no box account in this HOME: the 409 self case is skipped)")
            # the look's files: the tokens, the theme script and a font
            st, hd, raw = req(url, "GET", "/static/tokens.css")
            ok(st == 200 and b"--page:" in raw and b"@font-face" in raw, "tokens.css is served", st)
            st, hd, raw = req(url, "GET", "/static/theme.js")
            ok(st == 200 and b"spark-theme" in raw, "theme.js is served", st)
            st, hd, raw = req(url, "GET", "/static/fonts/monaspace-neon-400.woff2")
            ok(st == 200 and hd.get("Content-Type") == "font/woff2" and raw[:4] == b"wOF2", "a font is served as font/woff2", st)
            st, _, _ = req(url, "GET", "/static/fonts/monaspace-neon-400.woff2", headers={"If-None-Match": hd.get("ETag", "")})
            ok(st == 304, "a font comes back 304 on its ETag", st)
            st, _, _ = req(url, "GET", "/static/fonts/../spark.js")
            ok(st in (400, 404), "a path outside the static map is refused", st)
            st, _, raw = req(url, "GET", "/api/me", headers=bearer)
            dm = json.loads(raw)
            ok(st == 200 and isinstance(dm.get("faces"), dict) and dm["faces"].get("idle") and isinstance(dm.get("blink"), int),
               "/api/me carries the machine's faces and the blink rate", raw[:160])

            # kept threads: a program keeps a thread with no model turn, in
            # its OWN store (kept/ beside threads/); SPARK_HISTORY and a
            # clear never reach it, and an append says whether it was kept.
            # The forge runs with forge.KEEP_MAX = KEEP_MAX (FORGE_WRAP).
            from spark import forge as _forge
            HMAX = _forge.HISTORY_MAX_CHARS
            akept = state + "/users/ualice/kept/"
            SEEN.clear()
            st, _, raw = req(url, "POST", "/api/threads", {}, headers=upost)
            d = json.loads(raw)
            kid = str(d.get("id", ""))
            ok(st == 201 and d.get("kept") is True and re.fullmatch(r"\d{4}-\d\d-\d\d-\d{6}(-\d+)?", kid)
               and os.path.isfile(akept + kid + ".sealed") and oct(os.stat(akept + kid + ".sealed").st_mode & 0o777) == "0o600"
               and oct(os.stat(akept).st_mode & 0o777) == "0o700"
               and open(akept + kid + ".sealed").read() == "spark-sealed-v1 thread %s\n" % kid and not SEEN,
               "POST /api/threads {}: 201, a minted id, kept/ 0700, the file 0600, header only, no model turn", (st, raw[:120]))
            st, _, raw = req(url, "POST", "/api/threads", {"id": "notes-1"}, headers=upost)
            st2, _, raw2 = req(url, "POST", "/api/threads", {"id": "notes-1"}, headers=upost)
            ok(st == 201 and json.loads(raw) == {"id": "notes-1", "kept": True}
               and st2 == 200 and json.loads(raw2) == {"id": "notes-1", "kept": True},
               "POST /api/threads {id}: 201 made, the same id again 200 as it is", (st, st2, raw2[:80]))
            st, _, raw = req(url, "POST", "/api/threads", {"id": "notes-1"}, headers=bearer)
            ok(st == 403, "POST /api/threads without X-Spark -> 403 (the write gate)", st)
            st, _, raw = req(url, "POST", "/api/threads/notes-1/append", {"role": "user", "text": "note one"}, headers=upost)
            ok(st == 200 and json.loads(raw) == {"ok": True, "chars": 8, "cut": False},
               "append to a kept thread: 200 {ok, chars, cut false}", raw[:120])
            st, _, raw = req(url, "POST", "/api/threads/notes-1/append",
                             {"role": "assistant", "text": "y" * (HMAX + 5)}, headers=upost)
            ok(st == 200 and json.loads(raw) == {"ok": True, "chars": HMAX, "cut": True},
               "an append past the history cap is cut there and says so (cut true)", raw[:120])
            st, _, raw = req(url, "GET", "/api/threads/notes-1", headers=ubearer)
            ms = json.loads(raw).get("messages", [])
            ok(st == 200 and [m["text"][:8] for m in ms] == ["note one", "y" * 8] and len(ms[1]["text"]) == HMAX,
               "the kept thread reads back: 2 messages, the second at the cap", raw[:120])
            st, _, raw = req(url, "GET", "/api/threads?n=50", headers=ubearer)
            rows = json.loads(raw)["threads"]
            ok(st == 200 and any(t["id"] == "notes-1" and t["kept"] is True for t in rows)
               and all(t["kept"] is False for t in rows if t["id"] != "notes-1") and rows[0]["id"] != kid,
               "GET /api/threads rows say kept, and a header-only kept thread is not the newest", raw[:200])
            st, _, raw = req(url, "GET", "/api/threads/notes-1", headers=bbearer)
            ok(st == 404, "bob cannot read alice's kept thread", st)
            # a regular thread's id: moved to kept/, a rename -- the header is
            # the AAD, so every record still opens
            n_at = len(json.loads(req(url, "GET", "/api/threads/" + str(atid), headers=ubearer)[2])["messages"])
            st, _, raw = req(url, "POST", "/api/threads", {"id": atid}, headers=upost)
            st2, _, raw2 = req(url, "GET", "/api/threads/" + str(atid), headers=ubearer)
            ok(st == 200 and json.loads(raw) == {"id": atid, "kept": True} and os.path.isfile(akept + atid + ".sealed")
               and not os.path.exists(state + "/users/ualice/threads/" + atid + ".sealed")
               and st2 == 200 and n_at >= 2 and len(json.loads(raw2)["messages"]) == n_at,
               "a regular thread kept by its id: moved (200), every record still opens", (st, raw[:80], n_at))
            # an id in both directories is left as it is
            with open(state + "/users/ualice/threads/notes-1.sealed", "w") as f:
                f.write("spark-sealed-v1 thread notes-1\n")
            st, _, raw = req(url, "POST", "/api/threads", {"id": "notes-1"}, headers=upost)
            ok(st == 409 and json.loads(raw)["error"]["kind"] == "both", "an id in threads/ and kept/ at once -> 409 both", raw[:120])
            os.remove(state + "/users/ualice/threads/notes-1.sealed")
            # the id: 1 to 64 letters, digits, - and _, checked before any path
            sts = [req(url, "POST", "/api/threads", {"id": bad}, headers=upost)[0]
                   for bad in ("a" * 65, "../etc", "", "a.b", "a/b", 5)]
            ok(sts == [400] * 6, "POST /api/threads with a bad id (65 long, a path, empty, a dot, not a string) -> 400", sts)
            ok(req(url, "GET", "/api/threads/" + "a" * 65, headers=ubearer)[0] == 400,
               "GET /api/threads/<65 characters> -> 400")
            st, _, raw = req(url, "POST", "/api/threads", {"id": "a" * 64}, headers=upost)
            ok(st == 201, "a 64-character id is one", (st, raw[:80]))
            # a clear takes the regular threads and says how many kept stay
            nkept = len([f for f in os.listdir(akept) if f.endswith(".sealed")])
            st, _, raw = req(url, "DELETE", "/api/threads", headers=upost)
            d = json.loads(raw)
            ok(st == 200 and d.get("kept") == nkept == 4 and not os.listdir(state + "/users/ualice/threads")
               and len(os.listdir(akept)) == nkept,
               "DELETE /api/threads clears the regular threads, the kept ones stay and are counted", raw[:100])
            st, _, raw = req(url, "GET", "/api/users", headers=bearer)
            ua = next((u for u in json.loads(raw)["users"] if u["name"] == "ualice"), {})
            ok(st == 200 and ua.get("threads") == 2 and ua.get("kept") == 2,
               "/api/users counts alice's kept threads without her key (the 2 that hold a record)", ua)
            # SPARK_HISTORY=off: a regular thread refuses an append (409 off),
            # a kept one takes it, and a new kept thread is made
            spark_env = os.path.join(home, ".config", "spark", "spark.env")
            spark_was = open(spark_env).read() if os.path.exists(spark_env) else None
            with open(spark_env, "w") as f:
                f.write("SPARK_HISTORY=off\n")
            with open(state + "/users/ualice/threads/2020-02-02-000000.sealed", "w") as f:
                f.write("spark-sealed-v1 thread 2020-02-02-000000\n")
            try:
                st, _, raw = req(url, "POST", "/api/threads/2020-02-02-000000/append",
                                 {"role": "user", "text": "x"}, headers=upost)
                ok(st == 409 and json.loads(raw)["error"]["kind"] == "off",
                   "history off: an append to a regular thread -> 409 off, nothing stored", raw[:120])
                st, _, raw = req(url, "POST", "/api/threads/notes-1/append", {"role": "user", "text": "under off"},
                                 headers=upost)
                ok(st == 200 and json.loads(raw) == {"ok": True, "chars": 9, "cut": False},
                   "history off: a kept thread still takes an append", raw[:120])
                st, _, raw = req(url, "POST", "/api/threads", {"id": "made-while-off"}, headers=upost)
                ok(st == 201 and os.path.isfile(akept + "made-while-off.sealed"),
                   "history off: POST /api/threads still makes a kept thread", raw[:120])
            finally:
                if spark_was is None:
                    os.remove(spark_env)
                else:
                    with open(spark_env, "w") as f:
                        f.write(spark_was)
                os.remove(state + "/users/ualice/threads/2020-02-02-000000.sealed")
            # a kept thread whose file breaks cannot take an append: 500 store
            with open(akept + "made-while-off.sealed", "w") as f:
                f.write("spark-sealed-v1 thread someone-else\n")
            st, _, raw = req(url, "POST", "/api/threads/made-while-off/append", {"role": "user", "text": "x"},
                             headers=upost)
            ok(st == 500 and json.loads(raw)["error"]["kind"] == "store",
               "an append the store refuses (a foreign header) -> 500 store, never a quiet ok", raw[:120])
            # KEEP_MAX: bob keeps up to the cap, then 409 full; a kept id still answers
            bpost = dict(bbearer, **{"X-Spark": "1", "Origin": url})
            sts = [req(url, "POST", "/api/threads", {"id": "b%d" % i}, headers=bpost)[0] for i in range(KEEP_MAX)]
            st, _, raw = req(url, "POST", "/api/threads", {}, headers=bpost)
            ok(sts == [201] * KEEP_MAX and st == 409 and json.loads(raw)["error"]["kind"] == "full",
               "past KEEP_MAX kept threads a create -> 409 full", (sts, st, raw[:120]))
            ok(req(url, "POST", "/api/threads", {"id": "b0"}, headers=bpost)[0] == 200
               and sorted(os.listdir(state + "/users/ubob/kept")) == ["b%d.sealed" % i for i in range(KEEP_MAX)],
               "at the cap a kept id still answers 200, and bob's kept threads are his alone")
            # the admin keeps into the box account's own store
            st, _, raw = req(url, "POST", "/api/threads", {"id": "admin-kept"}, headers=post)
            ok(st == 201 and os.path.isfile(state + "/users/owner/kept/admin-kept.sealed")
               and len(__import__("glob").glob(state + "/users/*/kept/admin-kept.sealed")) == 1,
               "the admin's kept thread lands in the box account's store", raw[:80])
            st, _, _ = req(url, "GET", "/api/soul", headers=ubearer)
            ok(st == 200, "user GET /api/soul 200", st)
            st, _, _ = req(url, "POST", "/api/soul", {"text": "Call yourself Fixture."}, headers=upost)
            ok(st == 403, "user POST /api/soul -> 403 (the soul is the box's one identity)", st)
            st, _, raw = req(url, "POST", "/api/memory", {"text": "a user fact"}, headers=upost)
            ok(st == 200, "user POST /api/memory 200", raw[:100])
            st, _, _ = req(url, "DELETE", "/api/memory/1", headers=upost)
            ok(st == 200, "user DELETE /api/memory/1 200", st)
            st, _, _ = req(url, "GET", "/api/check", headers=ubearer)
            ok(st == 200, "user /api/check 200", st)
            st, _, _ = req(url, "GET", "/api/stats?days=1", headers=ubearer)
            ok(st == 200, "user /api/stats 200", st)
            st, _, _ = req(url, "GET", "/api/bar", headers=ubearer, timeout=30)
            ok(st == 404, "user /api/bar 404 (gone with v1.97)", st)
            st, _, raw = req(url, "POST", "/v1/chat/completions",
                             {"messages": [{"role": "user", "content": "capital of France?"}], "stream": False}, headers=ubearer)
            ok(st == 200 and "Paris" in json.loads(raw)["choices"][0]["message"]["content"], "/v1 with the user bearer 200", raw[:200])
            st, _, _ = req(url, "GET", "/v1/models", headers=ubearer)
            ok(st == 200, "user /v1/models 200", st)
            for method, path, body in (("POST", "/api/run", {"verb": "model", "args": ["none"]}),
                                       ("GET", "/api/config", None),
                                       ("POST", "/api/do/propose", {"text": "x"}),
                                       ("POST", "/api/do/run", {"command": "echo hi"}),
                                       ("GET", "/api/bench", None), ("DELETE", "/api/users/nobody", {}),
                                       ("GET", "/api/serve", None), ("GET", "/api/gpu", None),
                                       ("POST", "/api/check/refresh", {})):
                st, _, raw = req(url, method, path, body, headers=upost if body is not None else ubearer)
                kind = ""
                try:
                    kind = json.loads(raw)["error"]["kind"]
                except (ValueError, KeyError):
                    pass
                ok(st == 403 and kind == "role", "user %s %s -> 403 role" % (method, path), (st, raw[:100]))
            # user events: check/bar/serve, never the log event
            uc = http.client.HTTPConnection(u.hostname, u.port, timeout=4)
            uc.request("GET", "/api/events", None, ubearer)
            ur = uc.getresponse()
            req(url, "GET", "/api/health")          # touches forge.log
            head = ""
            try:
                while len(head) < 8000:
                    line = ur.readline().decode()
                    if not line:
                        break
                    head += line
            except OSError:
                pass
            uc.close()
            ok("event: check" in head and "event: serve" in head and "event: log" not in head,
               "user /api/events: check and serve, never log", head[:300])

            # the verbs while it runs
            rc, out, _ = spark("forge", "--print-url")
            ok(rc == 0 and out.strip() == url + "/login", "--print-url: the login URL only (no tty)", out)
            rc, out, _ = spark("forge", "--print-url", "--show-token")
            ok(rc == 0 and out.splitlines()[1] == "token  " + token, "--print-url --show-token", out)
            ok("\u2588" not in out and "#t=" not in out,
               "piped --print-url: no QR block, no login link", out)

            # at a pty the QR and the link appear -- the block must be
            # exactly what spark.qr renders for the login link
            def at_pty(*args, extra=None):
                """(rc, every byte spark wrote) with a pty as its stdio.
                OPOST off on the slave: with ONLCR, macOS writes the CR of
                a newline, finds the output queue full for the LF, and
                writes the CR again on the retry -- a stray \\r inside the
                QR block whenever this reader falls behind (under load).
                The slave stays open here until spark has exited and the
                master is drained: nothing is lost to a hangup, and no
                sleep decides when the output is complete."""
                import pty as _pty
                import select as _select
                import termios as _termios
                m, s = _pty.openpty()
                a = _termios.tcgetattr(s)
                a[1] &= ~_termios.OPOST
                _termios.tcsetattr(s, _termios.TCSANOW, a)
                e = dict(env)
                e.update(extra or {})
                p = subprocess.Popen([sys.executable, SPARK] + list(args),
                                     stdout=s, stderr=s, stdin=s, env=e, close_fds=True)
                buf = b""
                deadline = time.time() + 60
                try:
                    while True:
                        gone = p.poll() is not None
                        # once spark is gone every byte it wrote is queued:
                        # drain without waiting, stop at the first empty poll
                        ready, _, _ = _select.select([m], [], [], 0 if gone else 0.05)
                        if ready:
                            buf += os.read(m, 65536)
                        elif gone:
                            break
                        elif time.time() > deadline:
                            p.kill()
                            p.wait()
                            break
                finally:
                    os.close(s)
                    os.close(m)
                return p.returncode, buf.decode("utf-8", "replace")

            sys.path.insert(0, os.path.join(REPO, "lib"))
            from spark import qr as _qr
            link = url + "/login#t=" + token
            rc, out = at_pty("forge", "--print-url")
            ok(rc == 0 and out.splitlines()[0] == url + "/login"
               and "token  " + token in out, "--print-url at a pty: url and token", out[:200])
            ok(_qr.render(link, ascii_=False) in out or _qr.render(link, ascii_=True) in out,
               "--print-url at a pty: the QR is qr.render of the login link", repr(out[:1200]))
            ok("scan:" in out and link in out, "--print-url at a pty: the scan line and the link", out[-300:])
            rc, out = at_pty("forge", "--print-url", "--no-qr")
            ok(rc == 0 and "\u2588" not in out and "#t=" not in out
               and len([l for l in out.splitlines() if l.strip()]) == 2,
               "--print-url --no-qr: the two legacy lines", out)
            rc, out = at_pty("serve", "--login")
            ok(rc == 0 and out.splitlines()[0] == url + "/login" and "token  " + token in out
               and (_qr.render(link, ascii_=False) in out or _qr.render(link, ascii_=True) in out)
               and ("spark client " + url) in out and "spark user add NAME" in out,
               "serve --login at a pty: the url, the token, the QR, then how another machine joins", out[-300:])
            rc, out, _ = spark("serve", "--login")
            ok(rc == 0 and out.splitlines()[0] == url + "/login" and token not in out and "#t=" not in out,
               "serve --login piped: the url and the joining steps, never the token", out)

            rc, out = at_pty("user", "add", "qrguy")
            got_tok = ""
            for l in out.splitlines():
                s = l.strip()
                if len(s) == 43 and all(c.isalnum() or c in "-_" for c in s):
                    got_tok = s
            ok(rc == 0 and got_tok, "user add at a pty: a token printed", out[:200])
            ok(_qr.render(url + "/login#t=" + got_tok, ascii_=False) in out
               or _qr.render(url + "/login#t=" + got_tok, ascii_=True) in out,
               "user add at a pty: the QR is qr.render of that user's link")
            ok("scan on qrguy's phone" in out, "user add at a pty: the scan line", out[-200:])

            # the page carries the fragment-login wiring
            st, _, body = req(url, "GET", "/static/spark.js")
            body = body.decode("utf-8", "replace")
            ok(st == 200 and "history.replaceState" in body and "#t=" in body,
               "spark.js: the fragment login is wired (replaceState, #t=)")
            ok("confirmed: !!r.danger" in body, "spark.js: do/run carries confirmed after the second click")
            ok('el("pre", "block")' in body and 'r.command.indexOf("\\n") >= 0' in body,
               "spark.js: a block's command is shown in a <pre>, a line stays <code>")
            # a streamed answer follows the end only while the reader is at
            # the end: a reader who scrolled up is not pulled back (#73)
            ok("scrollTop = 1e9" not in body and "function atEnd(" in body
               and body.count("atEnd(") >= 4,
               "spark.js: the transcript and the output follow the end only from the end")
            rc, out, _ = spark("forge", "--print-url", "--user", "--show-token")
            ok(rc == 2 and "spark user add" in out, "--print-url --user: gone, names spark user add", out)
            rc, out, _ = spark("forge", "--print-client")
            ls = out.splitlines()
            ok(rc == 0 and ls[0] == "SITE_PEER_AI_URL=" + url and "spark user add NAME" in out
               and ("spark client " + url) in out and "spark user login NAME" in out
               and "the admin token stays on this machine" in out,
               "--print-client: mint here, client and login there, no secret", out)
            ok(token not in out and "forge-token" not in out, "--print-client never hands out the admin token", out)
            rc, out, _ = spark("forge")
            ok(rc == 0 and ("page     " + url + "/login") in out and "stub-7b-q4" in out
               and "admin token" in out and "4 users" in out,   # alice, bob, the box account, qrguy (upage was removed)
               "spark forge (bare, the serve view): the page, the model, the admin token, the user count", out)
            rc, out2, _ = spark("serve")
            ok(rc == 0 and out2 == out, "bare spark serve is the same view", out2)
            rc, out, _ = spark("forge", "on")
            ok(rc == 0 and "already running" in out, "start while running: already running", out)

            # a client through the forge
            client = {"SPARK_BASE_URL": url, "SPARK_FORGE_TOKEN": token, "SPARK_API_KEY": ""}
            rc, out, _ = spark("brain", "--porcelain", extra=client)
            ok(rc == 0 and out.strip() == url + "\tstub-7b-q4\tforge", "spark brain --porcelain: url, model, forge", out)
            SEEN.clear()
            rc, out, _ = spark("line", "--cwd", "/tmp", "--shell", "zsh", stdin="? files bigger than 1G this week", extra=client)
            ok(rc == 0 and out.splitlines()[0] == "cmd\tfind . -type f -size +1G -mtime -7", "spark line through the forge: the cmd protocol", out)
            sys0 = SEEN.get("body", {}).get("messages", [{}])[0].get("content", "")
            ok(SEEN.get("body", {}).get("model") == "spark", "the line through the forge names the spark role", SEEN.get("body", {}).get("model"))
            ok("Fixture" not in sys0 and sys0.startswith("You are spark, the assistant at") and "shell zsh" in sys0
               and "typed a question at the shell prompt" in sys0,
               "a spark request passes the forge untouched: machine facts and the mode, no identity", sys0[:200])
            SEEN.clear()
            rc, out, _ = spark("what", "does", "this", "mean", extra=client)
            sys0 = SEEN.get("body", {}).get("messages", [{}])[0].get("content", "")
            ok(rc == 0 and SEEN.get("body", {}).get("model") == "ember" and sys0.startswith("Call yourself Fixture.")
               and "You are spark, the assistant at" in sys0,
               "a sentence through the forge: ember, the identity then the client's prefix", sys0[:200])
            rc, out, _ = spark("brain", "--porcelain", extra=dict(client, SPARK_FORGE_TOKEN="wrong"))
            ok(rc == 0, "brain needs no token (health is open)", out)
            rc, out, _ = spark("line", stdin="x?", extra=dict(client, SPARK_FORGE_TOKEN="wrong"))
            ok(rc == 1 and "spark user" in out, "a wrong forge token -> error naming spark user", out)
            rc, out, _ = spark("status", extra=client)
            ok(rc == 0 and "(the page too)" in out, "spark status names the page's server", out)

            # token rotation takes effect live, one principal at a time
            rc, out, _ = spark("forge", "token", "--new", "--user")
            ok(rc == 2 and "spark user token --new" in out, "forge token --new --user: gone, names spark user", out)
            st, _, raw = req(url, "POST", "/api/user/token", {}, headers=upost)
            drot = json.loads(raw)
            utoken2 = drot.get("token", "")
            ok(st == 200 and utoken2 and utoken2 != utoken, "POST /api/user/token: a fresh token, returned once", raw[:80])
            ok(set(drot) == {"token", "link", "qr"} and drot["link"].endswith("/login#t=" + utoken2) and drot["qr"] == _qr.encode(drot["link"]),
               "POST /api/user/token: the login link and its QR too (v1.97)", sorted(drot))
            st, _, _ = req(url, "POST", "/api/user/token", {}, headers=dict(bearer, **{"X-Spark": "1", "Origin": url}))
            ok(st == 403, "the admin has no personal token to rotate here", st)
            st, _, _ = req(url, "GET", "/api/check", headers=ubearer)
            ok(st == 401, "the old user bearer died with the rotation")
            st, _, _ = req(url, "GET", "/api/check", headers=ucookie)
            ok(st == 401, "the old user cookie died too")
            st, _, _ = req(url, "GET", "/api/check", headers=cookie)
            ok(st == 200, "the admin cookie survived the user rotation")
            st, _, raw = req(url, "GET", "/api/me", headers={"Authorization": "Bearer " + utoken2})
            ok(st == 200 and json.loads(raw).get("role") == "user", "the new user token works without a restart", raw[:100])
            rc, out, _ = spark("serve", "--login", "--new")
            token2 = open(tok_path).read().strip()
            ok(rc == 0 and "admin" in out and "log in again" in out and token2 != token, "serve --login --new rewrites the file", out)
            last = audit_recs()[-1]
            ok(set(last) == {"ts", "ip", "action"} and last["action"] == "forge token" and last["ip"] == "cli",
               "spark forge token --new landed {ts, ip: cli, action}", last)
            ok(any(r.get("action") == "user token" and r.get("name") == "ualice" and r.get("ip") == "127.0.0.1"
                   and set(r) == {"ts", "ip", "action", "name"} for r in audit_recs()),
               "POST /api/user/token landed {ts, ip, action, name}")
            st, _, _ = req(url, "GET", "/api/check", headers=cookie)
            ok(st == 401, "the old admin cookie died with the old token")
            st, _, _ = req(url, "GET", "/api/check", headers={"Authorization": "Bearer " + token2})
            ok(st == 200, "the new admin token works without a restart")
            st, _, _ = req(url, "GET", "/api/check", headers={"Authorization": "Bearer " + utoken2})
            ok(st == 200, "the user token survived the admin rotation")

            # a second --foreground on the taken port: exit 1, and the
            # FIRST one's records survive (the url used to be written
            # before the bind, so the loser forget()'d the winner's)
            url_before = open(state + "/forge-url").read()
            pid_before = open(state + "/forge.pid").read()
            rc2, out2, err2 = spark("forge", "--foreground")
            ok(rc2 == 1 and "cannot bind" in (out2 + err2) and "records stay" in (out2 + err2),
               "a second --foreground on the taken port refuses, naming the running FORGE", out2 + err2)
            ok(os.path.exists(state + "/forge-url") and open(state + "/forge-url").read() == url_before
               and open(state + "/forge.pid").read() == pid_before,
               "the running FORGE's forge-url and forge.pid survive the failed second start")

            # a machine that holds only its own login (no admin token) still answers the line
            os.rename(tok_path, tok_path + ".aside")
            try:
                only = {"SPARK_BASE_URL": url, "SPARK_API_KEY": ""}
                rc, out, _ = spark("line", "--cwd", "/tmp", "--shell", "zsh", stdin="? files bigger than 1G this week", extra=only)
                ok(rc == 0 and out.splitlines()[0] == "cmd\tfind . -type f -size +1G -mtime -7",
                   "spark line with only the personal login answers the cmd protocol", out)
            finally:
                os.rename(tok_path + ".aside", tok_path)

            # lockout: ten wrong logins in a minute, then 429 -- on the
            # login and on a bearer alike, while a cookie (never a guess)
            # still opens. LAST, with the burst below: it poisons
            # 127.0.0.1 for a minute
            st, h3, _ = login(token2)
            cookie3 = {"Cookie": h3.get("Set-Cookie", "").split(";")[0]}
            ok(st == 200, "a fresh admin login after the rotation", st)

            def bad():
                login("nope")
            ts = [threading.Thread(target=bad) for _ in range(10)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            st, _, _ = login(token2)
            ok(st == 429, "after 10 wrong logins even the right one is 429", st)
            st, _, raw = req(url, "GET", "/api/me", headers={"Authorization": "Bearer " + token2})
            ok(st == 429 and json.loads(raw)["error"]["kind"] == "locked",
               "a locked-out address gets 429 on a right bearer too", (st, raw[:80]))
            st, _, _ = req(url, "GET", "/api/me", headers=cookie3)
            ok(st == 200, "a cookie is not a guess: the session still opens while locked out", st)

            # a burst of wrong logins: the sleepers are capped, the answers
            # come fast, and the lockout holds -- LAST here, because
            # it poisons 127.0.0.1 for a minute
            burst = []
            t0 = time.time()

            def _wrong():
                burst.append(login("wrong-burst")[0])
            ths = [threading.Thread(target=_wrong) for _ in range(6)]
            for th_ in ths:
                th_.start()
            for th_ in ths:
                th_.join(timeout=15)
            took = time.time() - t0
            ok(burst.count(401) + burst.count(429) == 6 and took < 5,
               "six wrong logins in parallel share the punish second, not six of them", (burst, round(took, 1)))
        finally:
            p.send_signal(signal.SIGTERM)
            try:
                p.wait(timeout=10)
                ok(p.returncode == 0, "SIGTERM ends the foreground forge (exit %s)" % p.returncode)
            except subprocess.TimeoutExpired:
                p.kill()
                ok(False, "foreground forge ignored SIGTERM")
        ok(not os.path.exists(state + "/forge-url") and not os.path.exists(state + "/forge.pid"), "forge-url and forge.pid removed")
        rc, out, _ = spark("forge", "off")
        ok(rc == 0 and "not running" in out, "stop afterwards: not running", out)

        # start / stop in the background
        rc, out, err = spark("forge", "on")
        ok(rc == 0 and "ready (pid" in out and url in out, "spark forge start: background, waits for health", out + err)
        try:
            st, _, _ = req(url, "GET", "/api/health")
            ok(st == 200, "the background forge answers")
            rc, out, _ = spark("forge", "off")
            ok(rc == 0 and "SPARK_FORGE=off" in out and "stopped" in out, "spark forge off: writes spark.env, stops", out)
            ok("SPARK_FORGE=off" in open(home + "/.config/spark/spark.env").read(), "spark.env has SPARK_FORGE=off")
            time.sleep(0.3)
            try:
                st, _, _ = req(url, "GET", "/api/health", timeout=2)
            except OSError:
                st = 0
            ok(st == 0, "the background forge is gone")
            rc, out, _ = spark("forge", "on")
            ok(rc == 0 and "SPARK_FORGE=on" in out and "ready (pid" in out, "spark forge on: writes spark.env, starts", out)
        finally:
            spark("forge", "off", "--force")
        rc, out, _ = spark("forge", "off")
        ok(rc == 0 and "not running" in out, "stopped for good", out)
        # v1.91: the page over TLS. A scratch pair from the openssl binary,
        # skipped with a notice where there is none, as shellcheck is
        exe = shutil.which("openssl")
        if not exe:
            print("  skip the page over TLS   (no openssl binary here)")
        else:
            tls_cases(ok, spark, env, home, state, exe)
        # v1.64: a unit here (runit, played by an sv stub under SPARK_OS=
        # Linux): `forge on` starts the page's server through it and waits
        # on its health -- never a Popen beside the unit
        svbins = os.path.join(tmp, "svbin")
        os.makedirs(svbins)
        os.makedirs(os.path.join(tmp, "runit"))
        with open(os.path.join(svbins, "sv"), "w") as f:
            f.write('#!/bin/sh\necho "sv $*" >> "$SV_LOG"\nd=$2; pf="$d/stub.pid"\n'
                    'alive() { [ -f "$pf" ] && kill -0 "$(cat "$pf")" 2>/dev/null; }\n'
                    'case $1 in\n'
                    '    status) [ -d "$d/supervise" ] || { echo "fail: $d: runsv not running"; exit 1; }\n'
                    '            if alive; then echo "run: $d: (pid $(cat "$pf")) 1s"; else echo "down: $d: 1s, normally up"; fi ;;\n'
                    '    up) alive || { "$SPARK_PY" "$SPARK_BIN" forge --foreground >> "$d/fg.log" 2>&1 & echo $! > "$pf"; } ;;\n'
                    '    down) if alive; then kill "$(cat "$pf")"; fi ;;\n'
                    'esac\nexit 0\n')
        os.chmod(os.path.join(svbins, "sv"), 0o755)
        svlog = os.path.join(tmp, "sv.log")
        fsvd = home + "/.config/spark/sv/spark-forge"
        os.makedirs(fsvd + "/supervise")
        open(fsvd + "/down", "w").close()
        unit = {"SPARK_OS": "Linux", "SPARK_ETC_RUNIT": os.path.join(tmp, "runit"), "SV_LOG": svlog,
                "PATH": svbins + ":" + env["PATH"], "SPARK_PY": sys.executable, "SPARK_BIN": SPARK}
        rc, out, err = spark("forge", "on", extra=unit)
        calls = open(svlog).read() if os.path.exists(svlog) else ""
        try:
            upid = int(open(fsvd + "/stub.pid").read())
        except (OSError, ValueError):
            upid = 0
        fpid = open(state + "/forge.pid").read().strip() if os.path.exists(state + "/forge.pid") else ""
        ok(rc == 0 and "ready" in out and ("sv up " + fsvd) in calls and not os.path.exists(fsvd + "/down")
           and upid and fpid == str(upid),
           "a unit here: forge on starts it through sv up and waits on health; the page's server is the unit's pid, no Popen",
           out + err + calls + " unit %s forge.pid %s" % (upid, fpid))
        ok(oct(os.stat(state + "/forge.pid").st_mode & 0o777) == "0o600", "forge.pid is 0600")
        rc, out, err = spark("forge", "off", extra=unit)
        gone = False
        for _ in range(30):
            try:
                os.kill(upid, 0)
            except OSError:
                gone = True
                break
            time.sleep(0.2)
        ok(rc == 0 and gone and ("sv down " + fsvd) in open(svlog).read(), "forge off: sv down, the unit's server gone", out + err)
        shutil.rmtree(home + "/.config/spark/sv")
        os.remove(state + "/serve-url")
        rc, out, err = spark("forge", "--foreground")
        ok(rc == 78 and "no model" in err, "no serve-url, no engine, no model -> 78", err)

    stub.shutdown()
    print("forge_smoke: %s" % ("all ok" if not fails else "%d FAILED" % fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
