"""The pitch demo: one mission, several agents, every beat a real run.

    POST /api/demo      (workbench/server.py) -- runs it as a job, events streamed live
    .venv\\Scripts\\python -m workbench.demo      -- the same run, printed

The scenario -- which report, which question, which coding task -- is the one
thing fixed, in workbench/demo.yaml. Each beat calls the code the rest of the
workbench uses: run_inspection.run_job, library.search, the Router, coder.solve
in the sandbox. Nothing on screen is animated; every event comes from a run.

Events, in order (each a dict passed to `emit`):

    demo_start   title, request, plan_note, beats
    router       the Router's choice and every candidate's reason, per task
    beat_start   index, id, title, caption, agents
      ...        the beat's own events: run_start, stage_enter, stage, evidence,
                 decision, route, summary, run_end (inspection); library (search);
                 route, task, attempt_start, attempt, code_result (code)
    beat_end     index, id, outcome, seconds
    demo_end     seconds
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Callable

import yaml

from workbench import coder, coding_tasks, router, sandbox, tools
from workbench.run_inspection import JobConfig, run_job

ROOT = Path(__file__).resolve().parent.parent
SCENARIO = Path(__file__).resolve().parent / "demo.yaml"

Emit = Callable[[dict], None]


def scenario() -> dict:
    return yaml.safe_load(SCENARIO.read_text(encoding="utf-8"))


def router_view(tasks: list[str]) -> dict:
    """What "Why this model" shows: for each task, the choice and every candidate's reason (not logged)."""
    registry, sha = router.load_registry()
    running = router.running_models(registry)
    out = {}
    for task in tasks:
        d = router.choose(task, registry, sha, running)
        out[task] = {"description": registry["tasks"][task]["description"], "chosen": d.chosen,
                     "status": d.status, "reason": d.reason,
                     "candidates": [{"model": c.model, "eligible": c.eligible, "reason": c.reason,
                                     "evidence": c.evidence, "limits": c.limits} for c in d.candidates]}
    return out


def _inspection(beat: dict, emit: Emit) -> str:
    cfg = JobConfig(doc_id=beat["doc_id"], source=beat.get("source", "scan"),
                    scan_quality=beat.get("scan_quality", "medium"),
                    image=[ROOT / p for p in beat["image"]] if beat.get("image") else None,
                    inject_fault=beat.get("inject_fault"))
    return run_job(cfg, emit=emit)["end"]


def _library(beat: dict, emit: Emit) -> str:
    with tools.acting("librarian", emit, beat=beat["id"]):     # search only: its written answers are not qualified
        hits = tools.call("search_library", query=beat["question"], k=beat.get("k"))
    emit({"type": "library", "question": beat["question"],
          "hits": [{"citation": h.citation(), "doc_id": h.doc_id, "title": h.title, "heading": h.heading,
                    "origin": h.origin, "pages": list(h.pages), "text": h.text, "score": h.score,
                    "why": h.why} for h in hits]})
    return f"{len(hits)} passages cited"


def _code(beat: dict, emit: Emit) -> str:
    task = coding_tasks.TASKS[beat["task_id"]]
    decision = router.route("code", {"demo_beat": beat["id"], "coding_task": task.task_id})
    emit({"type": "route", "task": "code", "chosen": decision.chosen, "decision": decision.reason})
    if decision.chosen is None:
        emit({"type": "notice", "message": f"no model is qualified to write code: {decision.reason}"})
        return "no qualified model"
    if not (sandbox.docker_available() and sandbox.image_present()):
        emit({"type": "notice", "message": "the sandbox is not available (Docker is not running or its image is "
                                           "missing); the code step is skipped rather than run unsealed"})
        return "sandbox unavailable"
    emit({"type": "task", "task_id": task.task_id, "brief": task.brief, "max_attempts": task.max_attempts})
    result = coder.solve(task, decision.chosen, emit=emit)
    record = asdict(result)
    record.pop("attempts")
    emit({"type": "code_result", **record, "attempts": len(result.attempts), "summary": result.summary()})
    return result.summary()


BEATS = {"inspection": _inspection, "library": _library, "code": _code}


def run(emit: Emit) -> dict:
    s = scenario()
    started = time.monotonic()
    emit({"type": "demo_start", "title": s["title"], "request": s["request"], "plan_note": s["plan_note"],
          "beats": [{k: b[k] for k in ("id", "kind", "title", "caption", "agents")} for b in s["beats"]]})
    emit({"type": "router", "tasks": router_view(s["router_tasks"])})
    outcomes = []
    for i, beat in enumerate(s["beats"]):
        emit({"type": "beat_start", "index": i, "id": beat["id"], "title": beat["title"],
              "caption": beat["caption"], "agents": beat["agents"]})
        t = time.monotonic()
        outcome = BEATS[beat["kind"]](beat, emit)
        outcomes.append({"id": beat["id"], "outcome": outcome})
        emit({"type": "beat_end", "index": i, "id": beat["id"], "outcome": outcome,
              "seconds": round(time.monotonic() - t, 1)})
    seconds = round(time.monotonic() - started, 1)
    emit({"type": "demo_end", "seconds": seconds, "outcomes": outcomes})
    return {"seconds": seconds, "outcomes": outcomes}


def main() -> int:
    def show(e: dict) -> None:
        kind = e["type"]
        if kind in ("demo_start", "beat_start", "beat_end", "demo_end", "notice", "route", "decision"):
            print(json.dumps({k: v for k, v in e.items() if k not in ("beats", "caption")}, default=str)[:220])
        elif kind == "stage":
            print(f"    [{e['status']:4}] {e['agent']:26} {e['node']:15} -> {e['next']:13} {e['note']}")
        elif kind == "library":
            for h in e["hits"]:
                print(f"    cited: {h['citation']}  [{h['heading']}]")
        elif kind == "attempt":
            print(f"    coder attempt {e['n']}: {'PASS' if e['passed'] else 'fail'} {e['seconds']}s")
    run(show)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
