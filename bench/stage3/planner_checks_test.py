"""Does code hold the Planner's plans to the rules? Checked without a model.

    .venv\\Scripts\\python bench\\stage3\\planner_checks_test.py

The model is replaced by scripted replies, so what is tested is the code around
it: the catalogue, the checks, the regulated-request rule, a re-plan after failed
checks, the no-model path, and how a plan becomes the demo's beats.
Writes to logs/planner.jsonl, logs/agents.jsonl and logs/router_decisions.jsonl:
stop the service first (one writer per log).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mcp_servers.audit import LOG_DIR, verify  # noqa: E402
from workbench import demo, missions, planner, router  # noqa: E402

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    results.append(ok)
    print(f"  {'pass' if ok else 'FAIL'}  {label}" + (f"  -- {detail}" if detail and not ok else ""))


def step(kind: str, doc_id: str = "", question: str = "", task_id: str = "", why: str = "asked") -> dict:
    return {"kind": kind, "doc_id": doc_id, "question": question, "task_id": task_id, "why": why}


def reply(steps: list[dict], not_possible: str = "", parts: list[dict] | None = None) -> dict:
    """A reply whose parts agree with its steps, unless `parts` is given."""
    if parts is None:
        parts = ([{"text": f"part for {s['kind']}", "kind": s["kind"]} for s in steps]
                 + ([{"text": "the rest", "kind": "none"}] if not_possible else []))
    return {"parts": parts, "steps": steps, "not_possible": not_possible}


cat = planner.catalogue()
DEMO = demo.scenario()["request"]

print("catalogue")
check("step kinds come from orchestration.yaml", set(cat.step_kinds) == {"inspection", "library", "code", "reply"},
      str(list(cat.step_kinds)))
check("reports come from the corpus index, with their tags", cat.documents.get("insp_1002") == "R-2247"
      and len(cat.documents) == 12, str(len(cat.documents)))
check("every coding task has a purpose to show the Planner", set(cat.tasks) == {"cml_report", "remaining_life",
      "next_due_date"} and all(cat.tasks.values()), str(cat.tasks))
schema = planner.output_schema(cat)
props = schema["properties"]["steps"]["items"]["properties"]
check("the schema's only choices are the catalogue's", props["kind"]["enum"] == list(cat.step_kinds)
      and props["doc_id"]["enum"] == [""] + list(cat.documents) and props["task_id"]["enum"] == [""] + list(cat.tasks)
      and schema["properties"]["parts"]["items"]["properties"]["kind"]["enum"] == list(cat.step_kinds) + ["none"])
check("the library's documents are listed with their titles", len(cat.library) >= 1
      and all(f"- {d}: {t}" in planner.request_message("x", cat) for d, t in cat.library.items()), str(cat.library))
message = planner.request_message("Draft the note for {documents} and R-2247", cat)
check("the request and every report are shown", "R-2247" in message and all(d in message for d in cat.documents))
check("a request cannot fill in the catalogue's fields", "Draft the note for {documents} and R-2247" in message
      and "{step_kinds}" not in message and "{tasks}" not in message)

print("plans that pass")
good = reply([step("inspection", doc_id="insp_1002"), step("library", question="When must a report be escalated?"),
              step("code", task_id="next_due_date")])
problems, steps = planner.check(good, DEMO, cat)
check("the demo request: inspection, library, code", not problems and [s["kind"] for s in steps] ==
      ["inspection", "library", "code"], str(problems))
check("arguments a kind does not take are dropped", steps[0]["args"] == {"doc_id": "insp_1002"}, str(steps[0]))
check("a request that cannot be done: no steps, and why", not planner.check(reply([], "cannot order parts"),
      "Order replacement plates", cat)[0])
check("a question about approval notes is not regulated work", not planner.check(
      reply([step("library", question="Who may sign?")]), "Who may sign an approval note for a Major finding?", cat)[0])
check("a regulated request with no report named may be refused with a reason",
      not planner.check(reply([], "the request does not say which report"), "Draft the approval note.", cat)[0])
check("a greeting is a reply step", not planner.check(reply([step("reply", question="Hello!")]), "Hello!", cat)[0])
check("a step's title names the report's tag", planner.describe(steps[0], cat)["title"] ==
      "Read the R-2247 report and draft the approval note", planner.describe(steps[0], cat)["title"])

print("plans that are refused")


def refused(r, request: str, expect: str) -> None:
    problems, _ = planner.check(r, request, cat)
    check(f"refused: {expect}", any(expect in p for p in problems), str(problems))


refused(reply([step("inspection", doc_id="insp_1000")]), "Draft the approval note for R-2247.",
        "the request does not name E-4461")
refused(reply([step("inspection", doc_id="insp_1002")]), "Draft the approval note for R-22470.",
        "the request does not name R-2247")
refused(reply([step("inspection", doc_id="insp_9999")]), "Draft the note for R-9999.", "not in the Documents list")
refused(reply([step("email", why="send it")]), "Email the note.", "not a listed step kind")
refused(reply([step("library")]), "Which clause covers corrosion?", "needs question")
refused(reply([step("code", task_id="delete_files")]), "Write code.", "not in the list")
refused(reply([step("code", task_id="cml_report"), step("code", task_id="cml_report")]), "Write code.",
        "repeats an earlier step: one step can do several parts")
refused(reply([step("library", question=f"q{i}") for i in range(cat.max_steps + 1)]), "Search.",
        f"at most {cat.max_steps}")
refused(reply([]), "Do something.", "does not say why")
refused(reply([step("library", question="What does the SOP say?")]), "Draft the approval note for E-4461.",
        "needs a step of kind inspection")
refused("not json", "anything", "not the required JSON object")
refused(reply([step("reply", question="Is R-2247 fit for service?")]), "Is R-2247 fit for service?",
        "questions about the organisation's reports and documents")
refused(reply([step("reply", question="What does SOP-INSP-002 say about intervals?")]),
        "What does SOP-INSP-002 say about intervals?", "asks about SOP-INSP-002")
check("a part with no step passes when not_possible says why", not planner.check(
      reply([], "no report is named", parts=[{"text": "draft the approval note", "kind": "inspection"}]),
      "Draft the approval note.", cat)[0])
refused(reply([step("library", question="q")], parts=[{"text": "q", "kind": "library"},
                                                      {"text": "tell me the due date", "kind": "code"}]),
        "Which clause, and when is it due?", 'the part "tell me the due date" has no step')
refused(reply([step("library", question="q"), step("code", task_id="cml_report")],
              parts=[{"text": "which clause", "kind": "library"}]), "Which clause?", "no part of the request is")
refused(reply([step("library", question="q")], parts=[{"text": "q", "kind": "library"}, {"text": "email", "kind": "none"}]),
        "Which clause? Then email it.", "not_possible must say")
refused(reply([step("library", question="q")], "cannot email", parts=[{"text": "q", "kind": "library"}]),
        "Which clause?", "every part of the request has a step")
refused(reply([], "x", parts=[]), "Do something.", "lists no parts")

print("planning, with the model scripted")
calls: list[list[dict]] = []


class Scripted:
    def __init__(self, content: dict | str):
        self.content = content if isinstance(content, str) else json.dumps(content)

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {"message": {"content": self.content}}


def script(*replies):
    queue = list(replies)

    def chat(model, messages, agent, **extra):
        calls.append([dict(m) for m in messages])
        assert agent == "planner" and extra["format"]["properties"]["steps"], extra
        return Scripted(queue.pop(0))
    planner.agents.chat = chat


events: list[dict] = []
script(reply([step("inspection", doc_id="insp_1000")]), reply([step("inspection", doc_id="insp_1002")]))
p = planner.plan("Draft the approval note for R-2247.", model="scripted", emit=events.append)
check("wrong report, then re-planned: planned on attempt 2", p.outcome == "planned" and len(p.attempts) == 2,
      f"{p.outcome} {p.attempts}")
check("the first attempt saw 2 messages; the re-plan saw the failed plan and its problems",
      [a["messages_sent"] for a in p.attempts] == [2, 4] and "E-4461" in calls[-1][-1]["content"],
      str([a["messages_sent"] for a in p.attempts]))
check("the regulated pattern is recorded", p.regulated_by is not None)
kinds = [e["type"] for e in events]
check("emitted: Planner started, completed, then the plan", kinds == ["agent", "agent", "plan"]
      and events[0]["agent_id"] == "planner" and events[1]["phase"] == "completed", str(kinds))

events = []
script(reply([step("library", question="q")]), reply([step("code", task_id="cml_report")]))
p = planner.plan("Read the report for V-1668 and draft the approval note.", model="scripted", emit=events.append)
check("regulated request planned twice without the graph: nothing is planned", p.outcome == "failed checks"
      and not p.steps and "needs a step of kind inspection" in p.text, p.text)
check("the Planner's work is recorded as failed", any(e.get("phase") == "failed" for e in events))

script(reply([], "no step can order parts"))
p = planner.plan("Order replacement plates.", model="scripted")
check("nothing possible: outcome 'not possible', with the reason shown", p.outcome == "not possible"
      and "order parts" in p.text, p.text)

script("this is not JSON")
p = planner.plan("Draft the approval note for R-2247.", model="scripted")
check("a reply that is not JSON ends in error, and nothing runs", p.outcome == "error" and not p.steps, p.outcome)

real_route = router.route
planner.router.route = lambda task, context=None: router.Decision(task, None, "no qualified model",
                                                                  "no model has passed a qualification test", [], "")
events = []
p = planner.plan(DEMO, emit=events.append)
planner.router.route = real_route
check("no qualified model: nothing planned, and the Router's reason shown",
      p.outcome == "no qualified model" and "no model has passed" in p.text, p.text)
check("the Router's decision is emitted", any(e["type"] == "route" and e["task"] == "plan" for e in events))

print("from plan to beats")
script(good)
p = planner.plan(DEMO, model="scripted")
s = demo.scenario()
beats, note = demo.plan_beats(p, s)
check("demo, planned: planner steps with the damaged copy staged after the library step",
      [(b["kind"], b["planned_by"]) for b in beats] == [("inspection", "planner"), ("library", "planner"),
                                                        ("inspection", "scenario"), ("code", "planner")],
      str([(b["kind"], b["planned_by"]) for b in beats]))
check("the scenario's settings reach the planned report: medium scan, fault injected",
      beats[0]["scan_quality"] == "medium" and beats[0]["inject_fault"] == "render" and "on purpose" in beats[0]["caption"],
      str(beats[0]))
check("settings do not reach a report they do not name", "inject_fault" not in missions.beats_from_plan(
      planner.Plan("x", "planned", steps=[planner.describe({"kind": "inspection", "args": {"doc_id": "insp_1000"},
                                                             "why": "w"}, cat)]), s["step_settings"])[0])
check("the planned note says what is staged", "from the demo scenario" in note, note)
beats, note = demo.plan_beats(planner.Plan(DEMO, "no qualified model", text="No model is qualified to plan."), s)
check("demo, not planned: the scenario's beats, labelled, with the reason",
      [b["id"] for b in beats] == ["inspect", "library", "damaged", "code"]
      and all(b["planned_by"] == "scenario" for b in beats) and note.startswith("No model is qualified"), note)

print("earlier turns in the chat")
E4461 = {"request": "Draft the approval note for E-4461.", "plan": ["Read the E-4461 report and draft the approval note"],
         "not_possible": ""}
V3859 = {"request": "Draft the note for V-3859.", "plan": [], "not_possible": ""}
earlier = planner.turns([E4461, "junk", {"request": " "}], 3)
check("earlier turns are kept as plain text; malformed ones are dropped", earlier == [E4461], str(earlier))
kept = planner.turns([{"request": f"r{i}"} for i in range(10)], 3)
check("only the most recent turns are kept", [t["request"] for t in kept] == ["r7", "r8", "r9"], str(kept))
plain = planner.request_message("Now do the same for V-1668.", cat)
followup = planner.request_message("Now do the same for V-1668.", cat, earlier)
check("a first message is planned from exactly the qualified prompt", "Earlier in this conversation" not in plain
      and followup.endswith(plain))
check("earlier turns come before the request, with what was planned", "Draft the approval note for E-4461."
      in followup.split("Request:")[0] and "Read the E-4461 report" in followup.split("Request:")[0])
check("a report named only in an earlier turn may be used", not planner.check(
      reply([step("inspection", doc_id="insp_1007")]), "Draft it again.", cat, planner.history_text([V3859]))[0])
problems, _ = planner.check(reply([step("inspection", doc_id="insp_1000")]), "Draft it again.", cat,
                            planner.history_text([V3859]))
check("a report named nowhere in the chat is still refused",
      any("neither the request nor the earlier messages name E-4461" in p for p in problems), str(problems))
script(reply([step("inspection", doc_id="insp_1001")]))
p = planner.plan("Now do the same for V-1668.", model="scripted", history=[E4461])
check("a follow-up is one fresh conversation, the earlier turns inside its message",
      p.outcome == "planned" and p.attempts[0]["messages_sent"] == 2 and "E-4461" in calls[-1][1]["content"]
      and p.history == [E4461], f"{p.outcome} {p.attempts}")

print("a message that is not a task")
caps = planner.capabilities(cat)
check("help lists the step kinds, reports, coding tasks and library, from the catalogue",
      [k["kind"] for k in caps["kinds"]] == list(cat.step_kinds) and "R-2247" in caps["reports"]
      and len(caps["tasks"]) == 3 and len(caps["library"]) == len(cat.library) and caps["intro"])
script(reply([], "a greeting is not something the workbench can do"))
events = []
planner.router.route = lambda task, context=None: router.Decision(task, "scripted", "chosen", "scripted", [], "")
missions.run("Hello", events.append)
planner.router.route = real_route
start = next((e for e in events if e["type"] == "mission_start"), {})
check("nothing planned: mission_start carries help, and no step runs", start.get("help") == caps
      and start.get("beats") == [] and not any(e["type"] == "beat_start" for e in events), str(start)[:300])

for log in ("planner.jsonl", "agents.jsonl"):
    ok, n, message = verify(LOG_DIR / log)
    check(f"logs/{log} chain intact ({n} entries)", ok, message)

print("all checks passed" if all(results) else f"{results.count(False)} check(s) FAILED")
raise SystemExit(0 if all(results) else 1)
