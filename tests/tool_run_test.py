#!/usr/bin/env python3
"""Task lifecycle and outcomes, without a model or changes to the machine."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from spark import tool_run as task


def reply(name, **arguments):
    return {"answer": "", "steps": [{"name": name, "arguments": arguments}]}


TOOLS = [{"name": "p0_out_level", "title": "out level N", "description": "Set output volume from 0 to 100.",
          "inputSchema": {"type": "object", "properties": {"level": {"type": "integer", "minimum": 0, "maximum": 100}},
                          "required": ["level"]}},
         {"name": "p1_notes_add", "title": "notes add TEXT", "description": "Create a note containing the supplied text.",
          "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}]


class Tasks(unittest.TestCase):
    def setUp(self):
        self.secret_patch = patch.object(task.do, "own_secrets", return_value=[])
        self.secret_patch.start()
        self.addCleanup(self.secret_patch.stop)
        self.request = {"version": 1, "goal": "set volume to 30 and note the result", "tools": copy.deepcopy(TOOLS),
                        "context": {"view": "Sound", "providers": [{"id": 0}, {"id": 1}],
                                    "clock": "2026-10-25T09:00:00-0500"}}

    def start(self, decision=None):
        return task.advance(self.request, lambda *_: decision or reply("p0_out_level", level=30))

    def follow(self, previous, decision, status="ok", result=None):
        req = dict(self.request, state=previous["state"], observation={"id": previous["id"], "status": status,
                   "result": result if result is not None else {"isError": status != "ok", "structuredContent": {"level": 30}}})
        return task.advance(req, decision if callable(decision) else lambda *_: decision)

    def test_cross_capability_task_uses_actual_result(self):
        first = self.start()
        self.assertEqual(first["status"], "step")
        seen = []
        def next_step(packet, _):
            observed = packet["history"][-1]["observation"]["result"]["structuredContent"]["level"]
            seen.append(observed)
            return reply("p1_notes_add", text="volume is %d" % observed)
        second = self.follow(first, next_step, result={"isError": False, "structuredContent": {"level": 27}})
        self.assertEqual(seen, [27])
        self.assertEqual(second["step"]["arguments"]["text"], "volume is 27")
        done = self.follow(second, reply("spark_task_finish", summary="volume changed and noted", evidence=[1, 2]))
        self.assertEqual(done["status"], "done")
        self.assertTrue(done["state"]["closed"])

    def test_unknown_write_stops_without_model_or_retry(self):
        first = self.start()
        def forbidden(*_):
            self.fail("an uncertain write must stop before inference")
        end = self.follow(first, forbidden, status="unknown")
        self.assertEqual(end["status"], "stopped")

    def test_single_action_finishes_from_receipt_without_another_model_call(self):
        first = self.start(dict(reply("p0_out_level", level=30), complete_after=True))
        end = self.follow(first, lambda *_: self.fail("success needs no completion inference"))
        self.assertEqual(end["status"], "done")
        self.assertEqual(end["evidence"], [1])
        self.assertEqual(end["summary"], "", "the native receipt already explains the result")

    def test_native_preparation_asks_without_inference_or_execution_evidence(self):
        first = self.start(dict(reply("p0_out_level", level=30), complete_after=True))
        asked = self.follow(first, lambda *_: self.fail("a native question needs no inference"),
                            status="needs_input", result={"question": "Which available output should I use?"})
        self.assertEqual(asked["status"], "ask")
        self.assertNotIn("evidence", asked)
        self.assertEqual(asked["state"]["history"][-1]["observation"]["status"], "needs_input")
        # Preparation executed nothing: the same arguments may be proposed
        # after the person resolves the missing precondition.
        next_ = task.advance(dict(self.request, state=asked["state"], answer="the speakers"), lambda *_: reply("p0_out_level", level=30))
        self.assertEqual(next_["status"], "step")

    def test_native_preparation_question_is_bounded(self):
        for result in ({}, {"question": 5}, {"question": "x" * 501}):
            with self.subTest(result=result), self.assertRaises(task.Invalid):
                self.follow(self.start(), lambda *_: self.fail("invalid question"), status="needs_input", result=result)

    def test_final_action_failure_still_needs_reassessment(self):
        first = self.start(dict(reply("p0_out_level", level=30), complete_after=True))
        end = self.follow(first, reply("spark_task_ask", question="The output is unavailable. Use another?"), status="error")
        self.assertEqual(end["status"], "ask")

    def test_cancel_stops_without_model(self):
        end = self.follow(self.start(), lambda *_: self.fail("cancelled"), status="cancelled")
        self.assertEqual(end["status"], "stopped")

    def test_mismatched_receipt_is_refused_before_model(self):
        first = self.start()
        req = dict(self.request, state=first["state"], observation={"id": 99, "status": "ok", "result": {}})
        with self.assertRaises(task.Invalid):
            task.advance(req, lambda *_: self.fail("mismatched receipt"))

    def test_cannot_replay_a_proposal_without_an_observation(self):
        with self.assertRaises(task.Invalid):
            task.advance(dict(self.request, state=self.start()["state"]), lambda *_: self.fail("no receipt"))

    def test_failure_can_lead_to_inspection_not_blind_retry(self):
        first = self.start()
        end = self.follow(first, reply("p0_out_level", level=30), status="error")
        self.assertEqual(end["status"], "blocked")
        inspected = self.follow(first, reply("spark_task_inspect", provider=0), status="error")
        self.assertEqual(inspected["status"], "inspect")

    def test_completed_write_is_not_duplicated_either(self):
        end = self.follow(self.start(), reply("p0_out_level", level=30))
        self.assertEqual(end["status"], "blocked")

    def test_completion_needs_successful_evidence(self):
        for evidence in ([], [1], [999]):
            with self.subTest(evidence=evidence):
                self.assertEqual(self.start(reply("spark_task_finish", summary="done", evidence=evidence))["status"], "blocked")
        end = self.follow(self.start(), reply("spark_task_finish", summary="done", evidence=[1]), status="error")
        self.assertEqual(end["status"], "blocked")

    def test_ask_keeps_goal_and_answer_in_same_task(self):
        first = self.start(reply("spark_task_ask", question="Which output?"))
        seen = []
        def decide(packet, _):
            seen.append(packet)
            return reply("p0_out_level", level=30)
        second = task.advance(dict(self.request, state=first["state"], answer="speakers"), decide)
        self.assertEqual(second["status"], "step")
        self.assertEqual(seen[0]["goal"], self.request["goal"])
        self.assertEqual(seen[0]["history"][-1]["answer"], "speakers")

    def test_structured_error_cannot_be_reported_as_success(self):
        with self.assertRaises(task.Invalid):
            self.follow(self.start(), reply("spark_task_finish", summary="done", evidence=[1]), result={"isError": True})

    def test_malformed_and_multiple_model_actions_are_refused(self):
        for decision in ({}, [], {"steps": None}, {"answer": "I will create it", "steps": [], "complete_after": False},
                         reply("p0_out_level", level=900),
                         {"steps": [reply("p0_out_level", level=30)["steps"][0]] * 2}):
            with self.subTest(decision=decision):
                end = task.advance(self.request, lambda *_: decision)
                self.assertEqual(end["status"], "blocked")

    def test_descriptions_survive_and_credentials_do_not(self):
        req = copy.deepcopy(self.request)
        req["context"]["password"] = "fixture-secret"
        req["tools"][0]["inputSchema"]["properties"]["password"] = {"type": "string", "format": "password"}
        def decide(packet, tools):
            data = json.dumps(packet)
            self.assertIn("Set output volume", data)
            self.assertNotIn("fixture-secret", data)
            self.assertNotIn('"password"', data)
            return reply("p0_out_level", level=30)
        self.assertEqual(task.advance(req, decide)["status"], "step")

    def test_duplicate_and_reserved_capabilities_refused(self):
        for tools in ([TOOLS[0], TOOLS[0]], [task.CONTROLS[0]]):
            with self.assertRaises(task.Invalid):
                task.advance(dict(self.request, tools=tools), lambda *_: self.fail("invalid capability"))

    def test_unknown_provider_cannot_be_inspected(self):
        self.assertEqual(self.start(reply("spark_task_inspect", provider=900))["status"], "blocked")

    def test_controls_only_offer_available_providers_and_supported_completion(self):
        def initial(packet, tools):
            names = [t.name for t in tools]
            self.assertNotIn("spark_task_finish", names)
            inspect = next(t for t in tools if t.name == "spark_task_inspect")
            self.assertEqual(inspect.schema["properties"]["provider"]["enum"], [0, 1])
            return reply("p0_out_level", level=30)
        first = task.advance(self.request, initial)
        def after_error(packet, tools):
            self.assertNotIn("spark_task_finish", [t.name for t in tools])
            return reply("spark_task_answer", text="the device is unavailable")
        self.assertEqual(self.follow(first, after_error, status="error")["status"], "answer")
        def empty(packet, tools):
            self.assertNotIn("spark_task_inspect", [t.name for t in tools])
            return reply("spark_task_answer", text="no provider is available")
        req = dict(self.request, context={"providers": []})
        self.assertEqual(task.advance(req, empty)["status"], "answer")

    def test_context_limit_is_explicit(self):
        with self.assertRaises(task.Invalid):
            task.advance(dict(self.request, context={"text": "a" * 25000}), lambda *_: self.fail("oversized context"))

    def test_closed_task_cannot_resume(self):
        end = self.start(reply("spark_task_answer", text="no matching capability"))
        with self.assertRaises(task.Invalid):
            task.advance(dict(self.request, state=end["state"]), lambda *_: self.fail("closed task"))

    def test_turn_limit_stops_before_inference(self):
        decision = reply("spark_task_ask", question="Which output?")
        current = self.start(decision)
        for _ in range(task.TURNS_MAX - 1):
            current = task.advance(dict(self.request, state=current["state"], answer="speakers"), lambda *_: decision)
        end = task.advance(dict(self.request, state=current["state"], answer="speakers"), lambda *_: self.fail("turn limit"))
        self.assertEqual(end["status"], "blocked")

    def test_malformed_continuation_is_a_protocol_error(self):
        for change in ({"goal": 12}, {"closed": "no"}, {"history": [None]}, {"pending": {"kind": "ask", "id": 999}}):
            with self.subTest(change=change), self.assertRaises(task.Invalid):
                state = dict(self.start()["state"], **change)
                task.advance(dict(self.request, state=state), lambda *_: self.fail("invalid continuation"))



if __name__ == "__main__":
    unittest.main()
