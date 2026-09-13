"""Are agents held to their tool lists? The gate in workbench/tools.py, checked without a model.

    .venv\\Scripts\\python bench\\stage3\\tool_gate_test.py

Real tools run where a call is allowed (the ground-truth stand-in, the rules
engine), so an allowed call is shown to work, not only a refused one to fail.
Writes to logs/agents.jsonl: stop the service first (one writer per log).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mcp_servers.audit import LOG_DIR, verify  # noqa: E402
from workbench import agents, tools  # noqa: E402
from workbench.procedural_graph import Graph  # noqa: E402

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    results.append(ok)
    print(f"  {'pass' if ok else 'FAIL'}  {label}" + (f"  -- {detail}" if detail and not ok else ""))


def refusal(fn) -> str | None:
    try:
        fn()
    except tools.ToolNotAllowed as e:
        return str(e)
    return None


print("definitions")
defs = agents._all()
unknown = {a: [t for t in d.get("tools") or [] if t not in tools.TOOLS] for a, d in defs.items()}
check("every tool an agent lists exists", not any(unknown.values()), str(unknown))
graph = Graph.load(ROOT / "workbench" / "graphs" / "inspection.yaml")
unbound = [n for n, s in graph.nodes.items() if s["kind"] != "end" and s.get("agent_id") not in defs]
check("every stage of the inspection graph runs as a defined agent", not unbound, str(unbound))

print("refusals")
check("a tool call with no agent acting is refused", refusal(lambda: tools.call("apply_rules", ev=None)) is not None)
events: list[dict] = []
with tools.acting("rules_engine", events.append):
    why = refusal(lambda: tools.call("sandbox", files={"main.py": "print(1)"}))
check("the Rules Engine cannot reach the sandbox", why is not None)
check("the refusal is emitted live", any(e["type"] == "tool" and e["status"] == "refused" and e["tool"] == "sandbox"
                                         for e in events), str(events))
with tools.acting("coder"):
    check("the Coder cannot search the library", refusal(lambda: tools.call("search_library", query="x")) is not None)
with tools.acting("qa_checker"):
    check("the QA Checker cannot write a note", refusal(lambda: tools.call("write_note")) is not None)
with tools.acting("librarian"):
    check("a tool that does not exist is refused", refusal(lambda: tools.call("delete_files")) is not None)
try:
    with tools.acting("nobody"):
        pass
    check("an agent that is not defined cannot act", False)
except ValueError:
    check("an agent that is not defined cannot act", True)

print("allowed calls (real code, no model)")
events = []
with tools.acting("evidence_builder", events.append):
    ev = tools.call("ground_truth_stand_in", doc_id="insp_1002", scan_quality="medium")
with tools.acting("rules_engine", events.append):
    decision = tools.call("apply_rules", ev=ev)
check("stand-in evidence, then the rules: ESCALATE on insp_1002", decision.outcome == "ESCALATE", decision.outcome)
phases = [(e["agent_id"], e["phase"]) for e in events if e["type"] == "agent"]
check("lifecycle: started then completed, per agent",
      phases == [("evidence_builder", "started"), ("evidence_builder", "completed"),
                 ("rules_engine", "started"), ("rules_engine", "completed")], str(phases))
calls = [(e["agent_id"], e["tool"], e["status"]) for e in events if e["type"] == "tool"]
check("each call is emitted with its agent", calls == [("evidence_builder", "ground_truth_stand_in", "ok"),
                                                      ("rules_engine", "apply_rules", "ok")], str(calls))
with tools.acting("qa_checker"):
    try:
        tools.call("stamp_note", ev=ev, decision=decision, summary=None, run={}, out=ROOT / "never.docx",
                   qa_results=[("CML-03 current", False, "differs")])
        stamped = True
    except ValueError:
        stamped = False
check("a note cannot be stamped with a failed check", not stamped and not (ROOT / "never.docx").exists())

print("failures")
events = []
with tools.acting("coder", events.append) as act:
    act.fail("not accepted after 3 attempts")
try:
    with tools.acting("coder", events.append):
        raise RuntimeError("model unavailable")
except RuntimeError:
    pass
failed = [e.get("reason") or e.get("error") for e in events if e.get("phase") == "failed"]
check("a failed piece of work and a crash are both recorded as failed",
      failed == ["not accepted after 3 attempts", "RuntimeError: model unavailable"], str(failed))
check("no agent is left acting afterwards", tools.current_agent() is None)

ok, n, message = verify(LOG_DIR / "agents.jsonl")
check(f"logs/agents.jsonl chain intact ({n} entries)", ok, message)

print("all checks passed" if all(results) else f"{results.count(False)} check(s) FAILED")
raise SystemExit(0 if all(results) else 1)
