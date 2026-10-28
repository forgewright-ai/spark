"""Bounded Pi sessions. The host alone owns transport, history and execution.

The child sees an empty home and the pinned SDK. It cannot read a person's
files, write sessions, spawn tools or connect to a server. Its only network
operation is a typed request over stdin/stdout; wire supplies the credentials
and enforces the configured origin and TLS policy, exactly as for other modes.
"""

import json
import os
import queue
import secrets
import signal
import socket
import subprocess
import tempfile
import threading
import time

from . import DATA_DIR, wire

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
WORKER = os.path.join(ROOT, "agent", "worker.mjs")
MESSAGE_MAX = 1048576
OUTPUT_MAX = 8388608


def runtime_dir():
    return os.path.abspath(os.environ.get("SPARK_AGENT_DIR") or os.path.join(DATA_DIR, "agent", "current"))


def runtime():
    root = os.path.realpath(runtime_dir())
    node, sdk = os.path.join(root, "node", "bin", "node"), os.path.join(root, "sdk")
    if not os.access(node, os.X_OK) or not os.path.isfile(os.path.join(sdk, "package-lock.json")):
        raise wire.BrainError("bad", "the agent is not installed -- run: spark do --agent on")
    from . import agent_runtime
    try:
        with open(os.path.join(root, "verified"), encoding="ascii") as f:
            if f.read().strip() != agent_runtime.pins()[2]:
                raise ValueError("old runtime")
    except (OSError, ValueError) as e:
        raise wire.BrainError("bad", "the agent needs an update -- run: spark do --agent on") from e
    return node, os.path.realpath(sdk)


def environment(home):
    # No inherited provider credentials, NODE_OPTIONS, extension paths or
    # proxy settings. Node receives no network permission in the first place.
    home = os.path.realpath(home)
    return {"HOME": home, "TMPDIR": home, "XDG_CONFIG_HOME": home,
            "XDG_DATA_HOME": home, "XDG_STATE_HOME": home, "PATH": "/usr/bin:/bin",
            "LANG": "C.UTF-8", "PI_OFFLINE": "1", "PI_TELEMETRY": "0"}


def command(node, sdk, home):
    node, sdk, home = (os.path.realpath(path) for path in (node, sdk, home))
    return [node, "--permission", "--no-addons", "--allow-fs-read=" + sdk,
            "--allow-fs-read=" + WORKER, "--allow-fs-read=" + home, WORKER, sdk]


def _body(message, session):
    """No arbitrary authenticated proxy, even if a child is compromised."""
    if (message.get("method") != "POST" or message.get("path") != "/v1/chat/completions"
            or type(message.get("body")) is not dict):
        raise ValueError("invalid model transport")
    body = message["body"]
    allowed = {"model", "messages", "stream", "stream_options", "max_tokens", "temperature",
               "tools", "tool_choice", "parallel_tool_calls", "chat_template_kwargs", "reasoning_budget_tokens"}
    if set(body) - allowed or not isinstance(body.get("messages"), list) or body.get("stream") is not True:
        raise ValueError("invalid model request")
    body = dict(body, model=session.role, cache_prompt=True)
    body["messages"] = [dict(m, content="".join(p["text"] for p in m["content"]))
                        if isinstance(m, dict) and isinstance(m.get("content"), list)
                        and all(isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("text"), str)
                                for p in m["content"]) else m for m in body["messages"]]
    data = wire._encode(body)
    if len(data) > MESSAGE_MAX:
        raise ValueError("model request limit")
    return data


def _stream(response, deliver, timings, progress):
    """Validate the same completion boundary as wire, preserving numeric stats.

    Pi's provider accepts EOF after finish_reason; Spark requires [DONE].
    Never send EOF to the SDK until that boundary has arrived from the host.
    """
    count, done, out = 0, False, []
    try:
        while True:
            raw = response.readline(MESSAGE_MAX + 1)
            if not raw:
                break
            progress[0] = time.monotonic()
            count += len(raw)
            if len(raw) > MESSAGE_MAX or count > OUTPUT_MAX:
                raise ValueError("model response limit")
            line = raw.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                done = True
                break
            try:
                chunk = json.loads(payload)
            except (ValueError, RecursionError):
                continue
            if not isinstance(chunk, dict):
                continue
            if "timings" in chunk or "usage" in chunk:
                timings.update(wire.timings_of(chunk))
            choices = chunk.get("choices", [])
            if not isinstance(choices, list):
                raise ValueError("invalid model choices")
            if choices and isinstance(choices[0], dict):
                choice = choices[0]
                if isinstance(choice.get("finish_reason"), str):
                    timings["finish"] = choice["finish_reason"]
                delta = choice.get("delta") or {}
                if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                    out.append(delta["content"])
            deliver("data: " + payload + "\n\n")
    except OSError as e:
        quiet = "timed out" in str(e)
        raise wire.BrainError("timeout" if quiet else "cut",
                              "the model went quiet -- the answer is incomplete" if quiet
                              else "the model stopped mid-reply -- the answer is incomplete") from e
    finally:
        wire._record(out, timings.get("finish") if done else None)
    if not done:
        raise wire.BrainError("cut", "the model stopped mid-reply -- the answer is incomplete")


def exchange(session, request, on_delta=None, timeout=None):
    node, sdk = runtime()
    request = dict(request, version=1, request_id=secrets.token_hex(16), model=session.role)
    ident = request["request_id"]
    initial = wire._encode(request) + b"\n"
    if len(initial) > MESSAGE_MAX:
        raise wire.BrainError("bad", "the agent request exceeds 1 MB -- send less")
    events, stop = queue.Queue(32), threading.Event()
    write_lock = threading.Lock()
    transports, responses = [], []
    errors = []
    wait = timeout or session.cfg.timeout
    started, progress = time.monotonic(), [time.monotonic()]
    phase = {"complete": True}
    timings = {}

    def put(event):
        while not stop.is_set():
            try:
                events.put(event, timeout=.1)
                return
            except queue.Full:
                pass

    with tempfile.TemporaryDirectory(prefix="spark-agent-") as home:
        try:
            child = subprocess.Popen(command(node, sdk, home), stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     cwd=home, env=environment(home), start_new_session=True)
        except OSError as e:
            raise wire.BrainError("bad", "the agent could not start -- run: spark do --agent on") from e

        def send(value):
            data = wire._encode(dict(value, request_id=ident)) + b"\n"
            with write_lock:
                if not stop.is_set():
                    child.stdin.write(data)
                    child.stdin.flush()

        def read():
            try:
                total = 0
                while not stop.is_set():
                    line = child.stdout.readline(MESSAGE_MAX + 1)
                    if not line:
                        break
                    total += len(line)
                    progress[0] = time.monotonic()
                    if len(line) > MESSAGE_MAX or total > OUTPUT_MAX or not line.endswith(b"\n"):
                        raise ValueError("agent output limit")
                    put(json.loads(line))
            except (OSError, ValueError, RecursionError):
                put({"event": "broken"})
            finally:
                put({"event": "eof"})

        def transport(message, response):
            try:
                send({"event": "headers", "id": message["id"]})
                _stream(response, lambda text: send({"event": "chunk", "id": message["id"], "data": text}), timings, progress)
                response.close()
                response = None
                phase["complete"] = True
                send({"event": "eof", "id": message["id"]})
            except wire.BrainError as e:
                errors.append(e)
            except (OSError, ValueError):
                errors.append(wire.BrainError("bad", "the agent's model stream ended unexpectedly"))
            finally:
                if response is not None:
                    response.close()
                if errors and not stop.is_set():
                    try:
                        send({"event": "transport_error", "id": message["id"]})
                    except OSError:
                        put({"event": "broken"})

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        try:
            child.stdin.write(initial)
            child.stdin.flush()
            calls, active = 0, None
            # Socket waits and the watchdog are quiet-time limits, not a cap
            # on a healthy long answer. Calls, tokens and bytes stay bounded.
            while time.monotonic() - progress[0] < wait:
                try:
                    message = events.get(timeout=.1)
                except queue.Empty:
                    continue
                if not isinstance(message, dict) or message.get("request_id") != ident:
                    if errors:
                        raise errors[0]
                    raise ValueError("agent protocol ended")
                event = message.get("event")
                if event == "request":
                    if errors:
                        raise errors[0]
                    calls += 1
                    if calls > 3 or message.get("id") != calls or not phase["complete"]:
                        raise ValueError("model call limit")
                    data = _body(message, session)
                    phase["complete"] = False
                    # Connect and wait for headers on the caller's thread:
                    # Ctrl-C interrupts urllib here, as on every other Spark
                    # request. Only reading an owned, cancellable socket moves
                    # to a thread, leaving the caller free to deliver deltas.
                    response = wire._send(session.cfg, session.url, data, wait,
                                          forge=session.forge, sent=session.note_sent)
                    responses.append(response)
                    progress[0] = time.monotonic()
                    active = threading.Thread(target=transport, args=(message, response), daemon=True)
                    transports.append(active)
                    active.start()
                elif event == "delta" and request["kind"] == "chat" and isinstance(message.get("text"), str):
                    if on_delta:
                        on_delta(message["text"])
                elif event == "result":
                    if errors:
                        raise errors[0]
                    if message.get("error") or not calls or message.get("calls") != calls or not phase["complete"]:
                        raise ValueError("agent returned no decision")
                    session.timings = dict(timings, finish=message.get("finish", timings.get("finish", "stop")))
                    return message, int((time.monotonic() - started) * 1000)
                else:
                    raise ValueError("invalid agent event")
            raise wire.BrainError("timeout", "the agent went quiet -- the answer is incomplete")
        except (BrokenPipeError, ConnectionResetError):
            raise
        except (OSError, ValueError) as e:
            raise wire.BrainError("bad", "the agent did not return a complete decision -- try again") from e
        finally:
            stop.set()
            # Closing the host's stdin also ends the child on parent death.
            # Kill the process group here so cancellation cannot leave a worker.
            if child.poll() is None:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            child.wait()
            for response in responses:
                try:
                    response.fp.raw._sock.shutdown(socket.SHUT_RDWR)
                except (AttributeError, OSError):
                    pass
            for thread in transports + [reader]:
                thread.join(timeout=1)
            for pipe in (child.stdin, child.stdout):
                try:
                    pipe.close()
                except OSError:
                    pass  # teardown cannot replace the caller's error


def options(session, kind, max_tokens):
    try:
        context = max(2048, int(wire.ctx(session.cfg)))
    except (ValueError, TypeError):
        context = 8192
    return {"kind": kind, "context_window": context, "max_tokens": max_tokens,
            "temperature": .2, "system": session._system()}


def chat(session, text, context, on_delta, max_tokens):
    messages = session._messages(text, context)
    request = dict(options(session, "chat", max_tokens), messages=messages[1:], tools=[])
    result, ms = exchange(session, request, on_delta)
    if not isinstance(result.get("text"), str):
        raise wire.BrainError("bad", "the agent returned no answer")
    return result["text"], ms


def task(session, packet):
    tools = []
    for tool in packet["tools"]:
        tool = dict(tool)
        if not tool["name"].startswith("spark_task_"):
            tool["properties"] = {"arguments": {"type": "object", "properties": tool["properties"],
                                               "required": tool["required"], "additionalProperties": False},
                                  "complete_after": {"type": "boolean", "description":
                                      "True only if this operation completes the goal when its native receipt succeeds."}}
            tool["required"] = ["arguments", "complete_after"]
        tools.append(tool)
    request = dict(options(session, "task", 900), packet=packet, tools=tools)
    result, _ = exchange(session, request)
    choice = result.get("choice", {})
    complete = False
    if isinstance(choice, dict) and not str(choice.get("name", "")).startswith("spark_task_"):
        args = choice.get("arguments", {})
        if not isinstance(args, dict) or type(args.get("complete_after")) is not bool:
            raise wire.BrainError("bad", "the agent returned no completion policy")
        complete = args["complete_after"]
        choice = {"name": choice.get("name"), "arguments": args.get("arguments")}
    return {"steps": [choice], "complete_after": complete}


PROPOSAL_GUIDANCE = "\nReturn the decision through spark_command_proposal, never as prose."


def proposal_tools(schema):
    return [{"name": "spark_command_proposal", "description":
              "Propose the next command for native review, or report done from actual observations. Executes nothing.",
              "properties": schema["properties"], "required": schema["required"]}]


def proposal_overhead(schema):
    return len(PROPOSAL_GUIDANCE) + len(json.dumps(proposal_tools(schema))) + 128


def propose(session, messages, schema, max_tokens):
    tools = proposal_tools(schema)
    request = dict(options(session, "command", max_tokens), messages=messages, tools=tools)
    request["system"] += PROPOSAL_GUIDANCE
    result, ms = exchange(session, request)
    choice = result.get("choice", {})
    if not isinstance(choice, dict) or choice.get("name") != "spark_command_proposal" or not isinstance(choice.get("arguments"), dict):
        raise wire.BrainError("bad", "the agent returned no command proposal")
    return choice["arguments"], ms
