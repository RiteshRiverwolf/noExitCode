"""Stop for a person, then resume exactly there -- the engine and the real pipeline, no model.

    .venv\\Scripts\\python bench\\stage3\\review_resume_test.py

1. The engine, with scripted stages on the inspection graph: a doubtful value
   pauses the run at review_values and nothing after it runs; resuming continues
   from that node, which runs once; re-measurement ends at needs_review; a run
   that cannot pause, or has nothing to ask, ends at needs_review.
2. The real pipeline on the blurred R-2247 scan (CML-03's last digit smudged,
   read as 12.3): it pauses and asks for CML-03 with its crop; entries that
   break the column's printed precision, lack a name, are not numbers, or name a
   value not under review are refused and the run keeps waiting; 12.32 entered
   by a named engineer resumes it to ESCALATE and a checked note that records
   the entry; a second run sent for re-measurement ends at needs_review.

Writes runs/ and the audit logs: stop the service first (one writer per log).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from docx import Document  # noqa: E402

from mcp_servers.audit import LOG_DIR, verify  # noqa: E402
from workbench import graph_engine  # noqa: E402
from workbench import procedural_graph as pg  # noqa: E402
from workbench import run_inspection as ri  # noqa: E402

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    results.append(ok)
    print(f"  {'pass' if ok else 'FAIL'}  {label}" + (f"  -- {detail}" if detail and not ok else ""))


# --- 1. the engine ---------------------------------------------------------------------
print("engine (scripted stages on the inspection graph)")
graph = pg.Graph.load(ri.GRAPH)


def scripted(log: list[str], ask: bool = True) -> dict:
    def stage(name: str):
        def handle(c: dict) -> pg.StageResult:
            log.append(name)
            if name == "build_evidence":
                c["review_request"] = {"items": [{"field": "CML-03.current_mm"}]} if ask else None
                return pg.StageResult("fail", "thickness values need a person: CML-03")
            if name == "review_values":
                d = c.pop("review_decision", None)
                if d is None:
                    return pg.StageResult("fail", "no one to ask")
                return pg.StageResult("ok" if d["action"] == "confirm" else "fail", d["action"])
            return pg.StageResult("ok", name)
        return handle
    return {n: stage(n) for n, s in graph.nodes.items() if s["kind"] != "end"}


log: list[str] = []
ex = graph_engine.Execution(graph, scripted(log), {}, pause_at_review=True)
r = ex.start()
check("a doubtful value pauses the run at review_values", r.end == "paused" and ex.paused_at == "review_values",
      f"{r.end} {ex.paused_at}")
check("nothing after the pause has run", log == ["read_document", "build_evidence", "build_evidence"], str(log))
r = ex.resume({"action": "confirm"})
check("resumed, it continues from review_values to done",
      r.end == "done" and log[3:] == ["review_values", "apply_rules", "write_summary", "render_note", "qa_check"],
      f"{r.end} {log}")
check("the trace is one path, review step included",
      [s.node for s in r.trace] == ["read_document", "build_evidence", "build_evidence", "review_values",
                                    "apply_rules", "write_summary", "render_note", "qa_check"],
      str([s.node for s in r.trace]))
try:
    ex.resume({"action": "confirm"})
    check("a finished run cannot be resumed again", False)
except RuntimeError:
    check("a finished run cannot be resumed again", True)

ex = graph_engine.Execution(graph, scripted([]), {}, pause_at_review=True)
ex.start()
check("sent for re-measurement, it ends at needs_review", ex.resume({"action": "remeasure"}).end == "needs_review")
check("a run that cannot pause ends at needs_review, as before",
      graph_engine.run(graph, scripted([]), {}).end == "needs_review")
check("with nothing a person could enter, it does not pause",
      graph_engine.Execution(graph, scripted([], ask=False), {}, pause_at_review=True).start().end == "needs_review")

# --- 2. the real pipeline ----------------------------------------------------------------
print("pipeline (blurred R-2247 scan, no model)")
IMAGE = [ROOT / "bench" / "stage1" / "partial" / "insp_1002_p1_blurred.png"]


def paused_run() -> tuple[dict, dict | None]:
    events: list[dict] = []
    out = ri.run_job(ri.JobConfig("insp_1002_damaged", image=IMAGE, no_model=True, pause_for_review=True),
                     emit=events.append)
    return out, next((e for e in events if e["type"] == "review"), None)


out, review = paused_run()
run_id = out["run_id"]
items = {i["field"]: i for i in review["items"]} if review else {}
item = items.get("CML-03.current_mm")
check("the run pauses", out["end"] == "paused", out["end"])
check("only CML-03's current thickness is asked", list(items) == ["CML-03.current_mm"], str(list(items)))
check("asked with what the scan read (12.3), its column's 2 decimals and the crop",
      bool(item) and item["read_as"] == "12.3" and item["decimals"] == 2 and bool(item["crop"]), str(item))
check("it waits among the paused runs", any(p["run_id"] == run_id for p in ri.paused_runs()))


def refusal(decision: dict) -> list[str] | None:
    try:
        ri.claim_review(run_id, decision)
    except ri.ReviewRefused as e:
        return e.problems
    return None


good = {"action": "confirm", "reviewer": "R. Test", "values": {"CML-03.current_mm": "12.32"}}
p = refusal({**good, "values": {"CML-03.current_mm": "12.3"}})
check("12.3 is refused: the column prints 2 decimals", bool(p) and "decimal" in p[0], str(p))
check("no name is refused", bool(refusal({**good, "reviewer": " "})))
check("'12,32' is refused: not a number as printed", bool(refusal({**good, "values": {"CML-03.current_mm": "12,32"}})))
check("a value not under review is refused",
      bool(refusal({**good, "values": {"CML-03.current_mm": "12.32", "CML-04.current_mm": "9.99"}})))
check("after refusals the run is still waiting", any(q["run_id"] == run_id for q in ri.paused_runs()))

claimed = ri.claim_review(run_id, good)
try:
    ri.claim_review(run_id, good)
    check("a paused run is taken only once", False)
except KeyError:
    check("a paused run is taken only once", True)

events: list[dict] = []
done = ri.continue_run(claimed, good, emit=events.append)
stages = [(e["node"], e["status"]) for e in events if e["type"] == "stage"]
decision = next((e for e in events if e["type"] == "decision"), {})
check("resumed, it runs to done", done["end"] == "done", f"{done['end']} {done.get('reason')}")
check("it continued from the review step, not from the start",
      stages[:2] == [("review_values", "ok"), ("apply_rules", "ok")] and ("read_document", "ok") not in stages,
      str(stages))
check("the rules escalate on CML-03 (12.32 below 12.70)",
      decision.get("outcome") == "ESCALATE" and any(t["subject"] == "CML-03" for t in decision.get("triggers", [])),
      str(decision.get("triggers")))
check("the read-back checks passed", ("qa_check", "ok") in stages, str(stages))
note = ROOT / done["note"] if done["note"] else None
cells = "\n".join(c.text for t in Document(note).tables for row in t.rows for c in row.cells) if note else ""
check("the note records who entered the value and what the scan read",
      "CML-03.current_mm = 12.32, entered by R. Test" in cells and "the scan read 12.3" in cells)
check("the review is saved in the run folder", (ROOT / done["folder"] / "02b_review_values" / "review.json").exists())

out2, _ = paused_run()
claimed = ri.claim_review(out2["run_id"], {"action": "remeasure", "reviewer": "R. Test"})
ended = ri.continue_run(claimed, {"action": "remeasure", "reviewer": "R. Test"})
check("sent for re-measurement: ends at needs_review, no note, reason given",
      ended["end"] == "needs_review" and ended["note"] is None and "re-measurement" in (ended["reason"] or ""),
      str(ended))

for name in ("workbench_runs.jsonl", "agents.jsonl"):
    ok, n, message = verify(LOG_DIR / name)
    check(f"{name} chain intact ({n} entries)", ok, message)

print("all checks passed" if all(results) else f"{results.count(False)} check(s) FAILED")
raise SystemExit(0 if all(results) else 1)
