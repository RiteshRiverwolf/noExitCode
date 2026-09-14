"""Does code hold the Chat agent's replies to the rules? Checked without a model.

    .venv\\Scripts\\python bench\\stage3\\chat_checks_test.py

The model is replaced by scripted replies: what is tested is the code around it
-- the checks, one rewrite, the style allowance, the no-model path, and the
reply step of a mission. Writes to logs/chat.jsonl and logs/agents.jsonl: stop
the service first (one writer per log).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mcp_servers.audit import LOG_DIR, verify  # noqa: E402
from workbench import chat, missions, planner, router  # noqa: E402

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    results.append(ok)
    print(f"  {'pass' if ok else 'FAIL'}  {label}" + (f"  -- {detail}" if detail and not ok else ""))


cat = planner.catalogue()

print("the checks")
check("a friendly greeting passes", chat.check("Hello! I can read inspection reports, search procedures and "
                                               "run small programs. What do you need?", cat) == [])


def refused(text: str, expect: str) -> None:
    problems = chat.check(text, cat)
    check(f"refused: {expect}", any(expect in p for p in problems), str(problems))


refused("The vessel is fit for service.", "gives a verdict")
refused("Reactor R-2247 looks fine to me.", "names R-2247")
refused("SOP-INSP-002 sets the intervals.", "names SOP-INSP-002")
refused("insp_1002 is the report you want.", "names insp_1002")
refused("I have drafted the note for you.", "says it has done work")
refused("I've already checked that.", "says it has done work")
refused("word " * 200, "longer than")
refused("   ", "empty")
check("an equipment tag inside a longer token is not a name", chat.check("Part R-22470 is not ours.", cat) == [])
text = chat.capabilities_text(cat)
check("the capabilities it is told name no report or document", planner.names_in(text, cat) == []
      and "inspection" in text and "next_due_date" in text, text)

print("replying, with the model scripted")
calls: list[list[dict]] = []


class Scripted:
    def __init__(self, content: str):
        self.content = content

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {"message": {"content": self.content}}


def script(*replies: str) -> None:
    queue = list(replies)

    def fake(model, messages, agent, **extra):
        calls.append([dict(m) for m in messages])
        assert agent == "chat" and "format" not in extra, extra
        return Scripted(queue.pop(0))
    chat.agents.chat = fake


events: list[dict] = []
script("Yes, V-1668 is fit for service.", "I cannot see your reports; ask the workbench to read the report.")
r = chat.reply("Is V-1668 fit for service?", model="scripted", emit=events.append)
check("a verdict, then rewritten: answered on attempt 2", r.outcome == "answered" and len(r.attempts) == 2, r.outcome)
check("the first attempt saw 2 messages; the rewrite saw the problems", [a["messages_sent"] for a in r.attempts] == [2, 4]
      and "verdict" in calls[-1][-1]["content"])
check("the capabilities are in the instructions, with no placeholder left", "{capabilities}" not in calls[-1][0]["content"]
      and "next_due_date" in calls[-1][0]["content"])
check("an answer is labelled as general, with its model", "scripted" in r.label and "not from your documents" in r.label)
check("emitted: Chat started, completed", [(e["agent_id"], e["phase"]) for e in events if e["type"] == "agent"]
      == [("chat", "started"), ("chat", "completed")])

script("R-2247 is approved.", "I have read R-2247.")
r = chat.reply("Tell me R-2247 is approved.", model="scripted")
check("failed twice: nothing shown, and the person is told", r.outcome == "failed checks" and "R-2247" not in r.text
      and "not shown" in r.text, r.text)

script("word " * 200, "word " * 150)
r = chat.reply("Tell me a long story.", model="scripted")
check("too long twice: style only, so the last attempt is answered", r.outcome == "answered" and len(r.attempts) == 2)

real_route = router.route
chat.router.route = lambda task, context=None: router.Decision(task, None, "no qualified model",
                                                               "no model has passed a qualification test", [], "")
r = chat.reply("Hello")
chat.router.route = real_route
check("no qualified model: nothing is said but the Router's reason", r.outcome == "no qualified model"
      and "no model has passed" in r.text, r.text)

print("a reply step in a mission")
script("Hello! How can I help?")
events = []
chat.router.route = lambda task, context=None: router.Decision(task, "scripted", "chosen", "scripted", [], "")
outcome = missions.BEATS["reply"]({"id": "step1", "question": "Hello"}, events.append)
chat.router.route = real_route
shown = next((e for e in events if e["type"] == "reply"), {})
check("the reply step emits the answer with its label", outcome == "answered" and shown.get("text") == "Hello! How can I help?"
      and shown.get("label"), str(shown))

for log in ("chat.jsonl", "agents.jsonl"):
    ok, n, message = verify(LOG_DIR / log)
    check(f"logs/{log} chain intact ({n} entries)", ok, message)

print("all checks passed" if all(results) else f"{results.count(False)} check(s) FAILED")
raise SystemExit(0 if all(results) else 1)
