"""The tool adapter of spark do. The host owns capabilities and execution.

One bounded JSON request returns one decision and a continuation. Only the
host carries that continuation, in memory; no desktop state is written to a
thread. A proposal is never an observation, and a transport failure is never
permission to retry a write. The decision function is replaceable without
changing this protocol or moving authorization into a model.
"""

import copy
import json
import os
import sys
import time

from . import agent, config, do, mcp, session, steps, wire

VERSION = 1
INPUT_MAX = 262144
STATE_MAX = 65536
CONTEXT_MAX = 24000
TOOLS_MAX = 128
TURNS_MAX = 12
PREFIX = "spark_task_"


class Invalid(ValueError):
    pass


def encoded(value):
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def clean(value, depth=0):
    """Bound nesting and hold secrets before any model request or continuation."""
    if depth > 12:
        raise Invalid("the task data is nested too deeply")
    if isinstance(value, str):
        return do.hold(mcp.scrub(value, "\n\t"))[0]
    if isinstance(value, list):
        return [clean(v, depth + 1) for v in value]
    if isinstance(value, dict):
        return {k: clean(v, depth + 1) for k, v in value.items() if not mcp.secret(k)}
    if value is None or isinstance(value, (int, float, bool)):
        return value
    raise Invalid("the task data must be JSON")


def control(name, description, properties, required):
    return {"name": PREFIX + name, "description": description,
            "inputSchema": {"type": "object", "properties": properties, "required": required}}


CONTROLS = [
    control("ask", "Ask the person for missing information. Never ask for a credential.",
            {"question": {"type": "string", "minLength": 1, "maxLength": 500}}, ["question"]),
    control("finish", "Report completion supported by successful observation ids. A proposal is not evidence.",
            {"summary": {"type": "string", "minLength": 1, "maxLength": 500},
             "evidence": {"type": "array", "items": {"type": "integer"}}}, ["summary", "evidence"]),
    control("answer", "Answer a question from observed facts, or explain why the goal cannot be achieved. Claims no execution.",
            {"text": {"type": "string", "minLength": 1, "maxLength": 500}}, ["text"]),
    control("inspect", "Read one available provider's current state before choosing an action. The provider id is in context.",
            {"provider": {"type": "integer", "minimum": 0}}, ["provider"]),
]


def capabilities(raw, provider_ids=None, can_finish=True):
    if not isinstance(raw, list) or len(raw) > TOOLS_MAX:
        raise Invalid("the task needs a tool list of at most 128 entries")
    controls = copy.deepcopy(CONTROLS)
    if not can_finish:
        controls = [c for c in controls if c["name"] != PREFIX + "finish"]
    if provider_ids is not None:
        if provider_ids:
            next(c for c in controls if c["name"] == PREFIX + "inspect")["inputSchema"]["properties"]["provider"]["enum"] = provider_ids
        else:
            controls = [c for c in controls if c["name"] != PREFIX + "inspect"]
    out, descriptions, names = [], [], set()
    for entry in raw + controls:
        if not isinstance(entry, dict):
            raise Invalid("a tool is not an object")
        name = entry.get("name", "")
        if entry in raw and (not isinstance(name, str) or name.startswith(PREFIX)):
            raise Invalid("a tool uses a reserved name")
        tool = mcp.tool_of("", entry, False)
        if tool is None or name in names:
            raise Invalid("a tool is invalid or its name is duplicated")
        names.add(name)
        args = steps.grammar_args(tool)
        try:
            wire.tools_gbnf([(name, args)], 1, task=True)
        except ValueError as e:
            raise Invalid("a tool schema is unsupported: " + name) from e
        out.append(tool)
        # Publish the same schema the grammar accepts. Descriptions are data,
        # not executable policy. Password fields never leave the host.
        props = {k: clean(p) for k, p, _ in args}
        descriptions.append({"name": name, "title": tool.title,
                             "description": clean(str(entry.get("description", "")))[:800],
                             "properties": props, "required": [k for k, _, req in args if req]})
    return out, descriptions


def stopped(state, message, status="blocked"):
    state["closed"] = True
    state.pop("pending", None)
    if len(encoded(state)) > STATE_MAX:
        state["history"] = []
        state["history_discarded"] = True
    return {"version": VERSION, "status": status, "summary": message, "state": state}


def advance(request, decide):
    """Pure task transition; decide receives goal, observations and capabilities.

    The continuation is host-owned, not an authorization token. A host must
    match observations to the outstanding proposal and enforce its own gates.
    """
    if not isinstance(request, dict) or request.get("version") != VERSION:
        raise Invalid("unsupported task protocol")
    context = clean(request.get("context", {}))
    if not isinstance(context, dict) or len(encoded(context)) > CONTEXT_MAX:
        raise Invalid("the task context is not an object within 24 kB")
    providers = context.get("providers", [])
    if (not isinstance(providers, list) or len(providers) > TOOLS_MAX
            or any(not isinstance(p, dict) or type(p.get("id")) is not int or p["id"] < 0 for p in providers)):
        raise Invalid("invalid provider catalogue")
    provider_ids = sorted(set(p["id"] for p in providers))
    state = clean(copy.deepcopy(request.get("state")))
    if state is None:
        goal = clean(request.get("goal", ""))
        if not isinstance(goal, str) or not goal.strip() or len(goal.encode()) > do.DO_GOAL_MAX:
            raise Invalid("the task needs a goal within 8 kB")
        state = {"version": VERSION, "goal": goal, "turn": 0, "history": [], "closed": False}
        if "observation" in request or "answer" in request:
            raise Invalid("a new task has no outstanding question or action")
    elif (not isinstance(state, dict) or state.get("version") != VERSION
          or not isinstance(state.get("goal"), str) or not isinstance(state.get("history"), list)
          or not state["goal"].strip() or len(state["goal"].encode()) > do.DO_GOAL_MAX
          or not isinstance(state.get("closed"), bool)
          or type(state.get("turn")) is not int or not 0 <= state["turn"] <= TURNS_MAX
          or len(encoded(state)) > STATE_MAX):
        raise Invalid("invalid task continuation")
    if state.get("closed"):
        raise Invalid("this task has ended")
    if (len(state["history"]) > TURNS_MAX or any(not isinstance(h, dict) or type(h.get("id")) is not int
            or ("observation" in h and not isinstance(h["observation"], dict))
            or ("decision" in h and not isinstance(h["decision"], dict)) for h in state["history"])):
        raise Invalid("invalid task history")
    pending = state.pop("pending", None)
    if pending:
        if (not isinstance(pending, dict) or type(pending.get("id")) is not int
                or pending["id"] != state["turn"] or pending.get("kind") not in ("ask", "inspect", "step")):
            raise Invalid("invalid pending decision")
        if pending.get("kind") == "ask":
            if not isinstance(pending.get("question"), str):
                raise Invalid("invalid pending question")
            answer = clean(request.get("answer", ""))
            if not isinstance(answer, str) or not answer.strip() or len(answer) > 2000:
                raise Invalid("the task is waiting for an answer")
            state["history"].append({"id": pending["id"], "question": pending["question"], "answer": answer})
        else:
            obs = clean(request.get("observation"))
            if not isinstance(obs, dict) or type(obs.get("id")) is not int or obs["id"] != pending.get("id"):
                raise Invalid("the observation does not match the outstanding action")
            status = obs.get("status")
            if status not in ("ok", "error", "unknown", "cancelled", "needs_input"):
                raise Invalid("the observation has no known status")
            if status == "ok" and (not isinstance(obs.get("result"), dict) or obs["result"].get("isError") is True):
                raise Invalid("a successful observation needs a non-error result")
            state["history"].append({"id": pending["id"], "decision": pending, "observation": obs})
            if status == "needs_input":
                question = obs.get("result", {}).get("question") if isinstance(obs.get("result"), dict) else None
                if pending["kind"] != "step" or not isinstance(question, str) or not question.strip() or len(question) > 500:
                    raise Invalid("preparation needs a bounded question for the person")
                if state["turn"] >= TURNS_MAX or len(encoded(state)) > STATE_MAX:
                    return stopped(state, "the task reached its continuation limit")
                state["turn"] += 1
                ident = state["turn"]
                state["pending"] = {"id": ident, "kind": "ask", "question": question}
                return {"version": VERSION, "status": "ask", "question": question, "state": state, "id": ident}
            if status in ("unknown", "cancelled"):
                return stopped(state, "the action's outcome is unknown; inspect it before retrying" if status == "unknown"
                               else "the task was cancelled", "stopped")
            if status == "ok" and pending.get("kind") == "step" and pending.get("complete_after") is True:
                # The provider's actual receipt is the answer. No model call
                # is needed to restate it. The host validates any output schema.
                result = stopped(state, "", "done")
                result["evidence"] = [pending["id"]]
                return result
    elif state["turn"]:
        raise Invalid("the task has no outstanding decision")
    if len(encoded(state)) > STATE_MAX:
        return stopped(state, "the task reached its context limit")
    if state["turn"] >= TURNS_MAX:
        return stopped(state, "the task reached its decision limit")
    last_observed = next((h for h in reversed(state["history"]) if "observation" in h), {})
    can_finish = last_observed.get("observation", {}).get("status") == "ok"
    tools, descriptions = capabilities(request.get("tools"), provider_ids, can_finish)
    # Stable capability semantics precede changing task data so the server
    # can reuse its prompt prefix across tasks with the same offered tools.
    packet = {"tools": descriptions, "goal": state["goal"], "context": context, "history": state["history"]}
    reply = decide(packet, tools)
    if not isinstance(reply, dict) or not isinstance(reply.get("steps"), list):
        return stopped(state, "the decision was not one valid action")
    if not isinstance(reply.get("complete_after", False), bool):
        return stopped(state, "the completion policy was not a boolean")
    kept, refused = steps.check(tools, reply)
    if refused or len(kept) != 1 or len(reply.get("steps", [])) != 1:
        return stopped(state, "the decision was not one valid action")
    call = kept[0]
    state["turn"] += 1
    ident = state["turn"]
    name, args = call["name"], call["arguments"]
    if name == PREFIX + "finish":
        evidence = args["evidence"]
        successful = {h["id"] for h in state["history"] if h.get("observation", {}).get("status") == "ok"}
        last = next((h for h in reversed(state["history"]) if "observation" in h), {})
        if (not evidence or not all(type(i) is int and i in successful for i in evidence)
                or last.get("observation", {}).get("status") != "ok"):
            return stopped(state, "completion has no matching successful evidence")
        result = stopped(state, args["summary"], "done")
        result["evidence"] = evidence
        return result
    if name == PREFIX + "answer":
        return stopped(state, args["text"], "answer")
    if name == PREFIX + "ask":
        state["pending"] = {"id": ident, "kind": "ask", "question": args["question"]}
        return {"version": VERSION, "status": "ask", "question": args["question"], "state": state, "id": ident}
    if name == PREFIX + "inspect":
        if args["provider"] not in provider_ids:
            return stopped(state, "the requested provider is unavailable")
        pending = {"id": ident, "kind": "inspect", "provider": args["provider"]}
    else:
        # A failed call is never blindly retried, even if the decision model
        # emits it again. Read new state or ask the person for a new task.
        if any(h.get("decision", {}).get("step") == call and h.get("observation", {}).get("status") != "needs_input"
               for h in state["history"]):
            return stopped(state, "this action was already attempted; inspect the result before starting another task")
        pending = {"id": ident, "kind": "step", "step": call, "complete_after": reply.get("complete_after", False)}
    state["pending"] = pending
    return dict(pending, version=VERSION, status=pending["kind"], state=state)


def model_decision(packet, tools):
    cfg = config.load()
    s = session.Session(cfg, "do-tools", os.path.basename(os.environ.get("SHELL") or "sh"), "", role="spark")
    msgs = s._messages("Choose the next action for this task.", encoded(packet))
    if len(msgs[-1]["content"]) > do.budget(cfg, len(msgs[0]["content"])):
        raise Invalid("the task exceeds the model context; offer fewer capabilities or a larger local context")
    started = time.monotonic()
    reply = s._retry_fresh(lambda: agent.task(s, packet))
    s.record(kind="do-tools", tools=len(tools), ms=int((time.monotonic() - started) * 1000))
    return reply


def main():
    try:
        raw = sys.stdin.buffer.read(INPUT_MAX + 1)
        if len(raw) > INPUT_MAX:
            raise Invalid("the task request exceeds 256 kB")
        request = json.loads(raw.decode("utf-8"))
        result = advance(request, model_decision)
        rc = 0
    except (ValueError, UnicodeError, wire.BrainError) as e:
        result = {"version": VERSION, "status": "blocked", "summary": mcp.short(str(e), 500)}
        rc = 2
    sys.stdout.write(encoded(result) + "\n")
    return rc
