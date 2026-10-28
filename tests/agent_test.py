#!/usr/bin/env python3
"""Real pinned Pi sessions with synthetic streams; no model or native writes."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from spark import agent, agent_runtime, do, tool_run, wire


def stream(text="hello", calls=None, finish=None, complete=True, error=None):
    delta = {"role": "assistant", "content": text}
    if calls is not None:
        delta = {"role": "assistant", "tool_calls": [dict(index=i, id="call_%d" % i, type="function",
                  function={"name": name, "arguments": args if isinstance(args, str) else json.dumps(args)})
                  for i, (name, args) in enumerate(calls)]}
    chunks = [{"choices": [{"index": 0, "delta": delta}]}]
    if error:
        chunks.append({"error": {"message": error, "code": "context_length_exceeded"}})
    else:
        chunks.append({"choices": [{"index": 0, "delta": {}, "finish_reason": finish or ("tool_calls" if calls else "stop")}],
                       "timings": {"prompt_n": 17, "predicted_n": 3, "predicted_per_second": 9.5, "cache_n": 4}})
    return ("".join("data: " + json.dumps(c) + "\n\n" for c in chunks)
            + ("data: [DONE]\n\n" if complete else "")).encode()


class Sessions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            agent.runtime()
        except wire.BrainError as e:
            print(str(e), file=sys.stderr)
            raise SystemExit(77)

    def setUp(self):
        self.sent, self.bodies, self.children = [], [], []
        # Use the production quiet-time allowance: shared Intel runners can
        # spend several seconds importing the SDK before any model request.
        self.s = SimpleNamespace(role="ember", cfg=SimpleNamespace(timeout=20), url="http://model.invalid", forge=False,
                                 note_sent=self.sent.append, _system=lambda: "Use only the supplied tools.")
        self.request = dict(kind="chat", context_window=8192, max_tokens=200, temperature=.2,
                            system="Answer the user.", messages=[{"role": "user", "content": "Hello"}], tools=[])
        self.received = []
        popen = subprocess.Popen

        def start(*a, **kw):
            child = popen(*a, **kw)
            if getattr(self, "eof_gap", 0):
                pipe, gap = child.stdin, self.eof_gap
                class DelayedTerminalEvent:
                    def __getattr__(self, name):
                        return getattr(pipe, name)

                    def write(self, data):
                        if json.loads(data).get("event") == "eof":
                            time.sleep(gap)
                        return pipe.write(data)
                child.stdin = DelayedTerminalEvent()
            self.children.append(child)
            self.assertNotIn("SPARK_API_KEY", kw["env"])
            self.assertNotIn("NODE_OPTIONS", kw["env"])
            self.assertNotIn("PI_PACKAGE_DIR", kw["env"])
            return child

        self.spawn = patch("spark.agent.subprocess.Popen", side_effect=start)
        self.spawn.start()
        self.addCleanup(self.spawn.stop)
        self.addCleanup(lambda: self.assertTrue(all(p.poll() is not None for p in self.children)))

    def run_request(self, responses, request=None, callback=None):
        def send(cfg, url, data, timeout, forge=False, sent=None):
            self.last_send_at = time.monotonic()
            self.assertEqual(timeout, self.s.cfg.timeout)
            self.bodies.append(json.loads(data))
            sent({"out_bytes": len(data), "dest": "model.invalid"})
            item = responses[min(len(self.bodies) - 1, len(responses) - 1)]
            return item() if callable(item) else io.BytesIO(item)
        with patch("spark.wire._send", side_effect=send):
            return agent.exchange(self.s, request or self.request, callback or self.received.append)

    def test_chat_stream_and_numeric_recording(self):
        result, _ = self.run_request([stream()])
        self.assertEqual((result["text"], self.received), ("hello", ["hello"]))
        self.assertEqual(self.s.timings["tg_tps"], 9.5)
        self.assertEqual(self.s.timings["pp_n"], 17)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.bodies[0]["model"], "ember")
        self.assertNotIn("tools", self.bodies[0])
        self.assertNotIn("tool_choice", self.bodies[0])

    def test_small_context_preserves_the_hosts_reply_budget(self):
        request = dict(self.request, context_window=4096)
        self.run_request([stream()], request=request)
        self.assertEqual(self.bodies[0]["max_tokens"], request["max_tokens"])

    def test_probe_resolves_temporary_directory_and_sdk_aliases(self):
        node, sdk = agent.runtime()
        with tempfile.TemporaryDirectory() as home:
            alias = os.path.join(home, "sdk")
            os.symlink(sdk, alias)
            agent_runtime.probe(node, alias)

    def test_missing_sentinel_keeps_partial_and_refuses_success(self):
        with self.assertRaises(wire.BrainError) as cm:
            self.run_request([stream(complete=False)])
        self.assertEqual(cm.exception.kind, "cut")
        self.assertEqual(self.received, ["hello"])
        self.assertEqual(len(self.bodies), 1)

    def test_compaction_waits_for_transport_close_and_only_displays_the_answer(self):
        self.eof_gap = .05
        class SlowClose(io.BytesIO):
            def close(self):
                time.sleep(.2)
                super().close()

        def response(text, prompt_tokens):
            chunks = [{"choices": [{"index": 0, "delta": {"role": "assistant", "content": text}}]},
                      {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": 10,
                                 "total_tokens": prompt_tokens + 10}}]
            data = "".join("data: " + json.dumps(c) + "\n\n" for c in chunks)
            return SlowClose((data + "data: [DONE]\n\n").encode())

        request = dict(self.request, context_window=2048, max_tokens=100, messages=[
            {"role": "user", "content": "Earlier context. " * 400},
            {"role": "assistant", "content": "Earlier answer. " * 300},
            {"role": "user", "content": "Current fixture question."}])
        result, _ = self.run_request([lambda: response("Compact fixture history.", 1800),
                                     lambda: response("Current answer.", 200)], request)
        self.assertEqual(len(self.bodies), 2)
        self.assertEqual(self.received, ["Current answer."])
        self.assertEqual(result["text"], "".join(self.received))

    def test_malformed_stream_fails_without_waiting_for_the_watchdog(self):
        for choices in ({"bad": "shape"}, True, 1):
            self.bodies.clear()
            raw = ("data: " + json.dumps({"choices": choices}) + "\n\ndata: [DONE]\n\n").encode()
            with self.subTest(choices=choices), self.assertRaises(wire.BrainError) as cm:
                self.run_request([raw])
            self.assertEqual(cm.exception.kind, "bad")
            self.assertEqual(len(self.bodies), 1)
            self.assertLess(time.monotonic() - self.last_send_at, self.s.cfg.timeout / 2)

    def test_consumer_cancellation_is_not_rewritten(self):
        for error in (KeyboardInterrupt, BrokenPipeError, ConnectionResetError):
            with self.subTest(error=error), self.assertRaises(error):
                self.run_request([stream()], callback=lambda _: (_ for _ in ()).throw(error()))

    def test_failed_turn_never_returns_an_old_answer_or_retries_visible_text(self):
        self.eof_gap = .05
        for history in (1, 10):
            self.bodies.clear()
            self.received.clear()
            messages = sum(([{"role": "user", "content": "Earlier question " + "x " * 250},
                             {"role": "assistant", "content": "Earlier answer " + "y " * 250}]
                            for _ in range(history)), []) + [{"role": "user", "content": "Current question"}]
            req = dict(self.request, messages=messages)
            with self.subTest(history=history), self.assertRaises(wire.BrainError):
                self.run_request([stream("Interrupted text.", error="context length exceeded")], req)
            self.assertEqual(self.received, ["Interrupted text."])
            self.assertEqual(len(self.bodies), 1)

    def test_native_proposal_is_only_a_choice(self):
        req = dict(self.request, kind="command", tools=[{"name": "native", "description": "Native proposal",
                   "properties": {"level": {"type": "integer"}}, "required": ["level"]}])
        result, _ = self.run_request([stream(calls=[("native", {"level": 30})])], req)
        self.assertEqual(result["choice"], {"name": "native", "arguments": {"level": 30}})
        self.assertEqual(len(self.bodies), 1)
        self.assertEqual(self.received, [])

    def test_command_completion_requires_a_structured_decision(self):
        done = {"kind": "done", "command": "", "hint": "Directory printed.", "danger": False, "proof": ""}
        req = dict(self.request, kind="command", tools=agent.proposal_tools(do.DO_SCHEMA),
                   messages=[{"role": "user", "content": "Print the current directory."},
                             {"role": "assistant", "content": "pwd\nPrint the current directory."},
                             {"role": "user", "content": "Exit 0. Output: /tmp/project"}])
        result, _ = self.run_request([stream(calls=[("spark_command_proposal", done)])], req)
        self.assertEqual(result["choice"]["arguments"], done)
        self.assertEqual(self.bodies[0].get("tool_choice"), "required")

    def test_incomplete_or_multiple_tool_calls_never_yield_a_proposal(self):
        req = dict(self.request, kind="command", tools=[{"name": "native", "description": "Native proposal",
                   "properties": {"level": {"type": "integer"}}, "required": ["level"]}])
        for payload in (stream("kind:done\nhint:finished"),
                        stream(calls=[("native", {"level": 30})], complete=False),
                        stream(calls=[("native", {"level": 30}), ("native", {"level": 40})]),
                        stream(calls=[("native", '{"level":')], finish="length")):
            self.bodies.clear()
            with self.subTest(payload=payload), self.assertRaises(wire.BrainError):
                self.run_request([payload], req)
            self.assertLessEqual(len(self.bodies), 3)

    def test_task_context_has_only_committed_observations(self):
        self.s.role = "spark"
        req = dict(self.request, kind="task", tools=[{"name": "spark_task_answer", "description": "Answer",
                   "properties": {"text": {"type": "string"}}, "required": ["text"]}], packet={
            "goal": "Read back the note", "context": {"view": "Notes"}, "history": [
                {"id": 1, "decision": {"kind": "step", "step": {"name": "native_add", "arguments": {"text": "Exact."}}},
                 "observation": {"id": 1, "status": "ok", "result": {"receipt": "Created exact note."}}}]})
        self.run_request([stream(calls=[("spark_task_answer", {"text": "The note says Exact."})])], req)
        messages = self.bodies[0]["messages"]
        observed = [m for m in messages if m["role"] == "tool"]
        self.assertEqual(len(observed), 1)
        self.assertIn("Created exact note.", observed[0]["content"])
        self.assertNotIn("Proposal handed", json.dumps(messages))
        self.assertNotIn("native_add", [t["function"]["name"] for t in self.bodies[0]["tools"]])
        self.assertNotIn("tool_choice", self.bodies[0])

    def test_unavailable_prose_is_not_completion_after_a_write(self):
        req = dict(self.request, kind="task", packet={"goal": "Finish", "context": {}, "history": [
            {"id": 1, "decision": {"kind": "step", "step": {"name": "native", "arguments": {}}},
             "observation": {"id": 1, "status": "ok", "result": {"receipt": "Done"}}}]})
        with self.assertRaises(wire.BrainError):
            self.run_request([stream("All done.")], req)

    def test_body_refuses_admin_proxy_and_foreign_fields(self):
        valid = {"method": "POST", "path": "/v1/chat/completions", "body": {"stream": True, "messages": []}}
        for bad in (dict(valid, path="/api/do/run"), dict(valid, method="GET"),
                    dict(valid, body=dict(valid["body"], url="https://elsewhere.invalid"))):
            with self.assertRaises(ValueError):
                agent._body(bad, self.s)

    def test_node_permissions_block_ambient_capabilities(self):
        node, _ = agent.runtime()
        code = """import fs from 'node:fs'; import net from 'node:net'; import cp from 'node:child_process';
const checks = [() => fs.readFileSync('/etc/passwd'), () => fs.writeFileSync('unexpected', 'x'),
() => cp.spawnSync('/bin/echo', ['bad'])];
for (const check of checks) { try { check(); process.exit(2); } catch (e) { if (e.code !== 'ERR_ACCESS_DENIED') throw e; } }
await new Promise((resolve, reject) => net.connect(1, '127.0.0.1').once('connect', () => reject(new Error('network allowed')))
  .once('error', e => e.code === 'ERR_ACCESS_DENIED' ? resolve() : reject(e)));
"""
        with tempfile.TemporaryDirectory() as home:
            result = subprocess.run([node, "--permission", "--no-addons", "--input-type=module", "-e", code],
                                    cwd=home, env=agent.environment(home), capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr.decode())


class Archives(unittest.TestCase):
    def archive(self, root, members):
        path = os.path.join(root, "package.tar")
        with tarfile.open(path, "w") as tar:
            for name, data in members:
                info = tarfile.TarInfo(name)
                info.size, info.mode = len(data), 0o644
                tar.addfile(info, io.BytesIO(data))
        return path

    def test_identical_npm_alias_is_allowed_but_conflicts_and_traversal_are_refused(self):
        for second, content, good in (("package/./index.js", b"same", True),
                                      ("package/./index.js", b"other", False),
                                      ("package/dir/../index.js", b"same", False)):
            with tempfile.TemporaryDirectory() as root:
                archive = self.archive(root, [("package/index.js", b"same"), (second, content)])
                dest = os.path.join(root, "out")
                if good:
                    agent_runtime._unpack(archive, dest)
                    self.assertEqual(Path(dest, "index.js").read_bytes(), b"same")
                else:
                    with self.assertRaises(ValueError):
                        agent_runtime._unpack(archive, dest)
                    self.assertFalse(os.path.exists(dest))

    def test_off_cannot_race_install_activation(self):
        with tempfile.TemporaryDirectory() as root:
            release = Path(root, "releases", "old")
            release.mkdir(parents=True)
            current = Path(root, "current")
            current.symlink_to(release)
            with patch("spark.agent.runtime_dir", return_value=str(current)):
                with agent_runtime.locked(root), self.assertRaisesRegex(ValueError, "another agent setup"):
                    agent_runtime.remove()
                self.assertTrue(current.is_symlink())
                agent_runtime.remove()
                self.assertFalse(current.exists())
                self.assertFalse(release.exists())

    def test_failed_setup_keeps_the_old_activation(self):
        with tempfile.TemporaryDirectory() as root:
            old = Path(root, "old")
            old.mkdir()
            current = Path(root, "current")
            current.symlink_to(old)
            part = {"url": "https://nodejs.org/fixture.tar.gz", "sha256": "0" * 64, "size": 1}
            def unpack(_archive, path):
                Path(path).mkdir(parents=True)
            with patch("spark.agent.runtime_dir", return_value=str(current)), \
                    patch("spark.agent_runtime.pins", return_value=(part, {"packages": {}}, "new")), \
                    patch("spark.agent_runtime.status", return_value="needs update"), \
                    patch("spark.agent_runtime._archive", return_value="fixture"), \
                    patch("spark.agent_runtime._unpack", side_effect=unpack), \
                    patch("spark.agent_runtime.probe", side_effect=ValueError("probe failed")):
                with self.assertRaisesRegex(ValueError, "probe failed"):
                    agent_runtime.install()
            self.assertEqual(current.resolve(), old.resolve())
            self.assertFalse(list(Path(root).glob(".install-*")))

    def test_convergence_retries_incomplete_runtime_and_returns_failure(self):
        with patch.dict(os.environ, {"SPARK_NO_APPLY": ""}), \
                patch("spark.agent_runtime.status", return_value="needs update"), \
                patch("spark.agent_runtime.main", side_effect=[2, 0]) as setup:
            self.assertEqual(agent_runtime.converge(), 2)
            self.assertEqual(agent_runtime.converge(), 0)
            self.assertEqual(setup.call_count, 2)


if __name__ == "__main__":
    unittest.main()
