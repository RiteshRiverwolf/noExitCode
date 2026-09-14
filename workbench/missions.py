"""Running a mission: a request planned by the Planner, then each step run by ordinary workbench code.

    POST /api/missions   (workbench/server.py)  a request in plain words, planned, checked, run
    workbench/demo.py                           the pitch demo: the same steps, with the scenario's settings

A step ("beat") is a dict: `kind` names the work -- inspection, library, code or
reply, the step kinds in orchestration.yaml -- and the rest are its arguments and
settings. Each kind calls the code the rest of the workbench uses:
run_inspection.run_job, library search, the Router, coder.solve in the sandbox,
chat.reply. Nothing on screen is animated; every event comes from a run.

Events, in order (each a dict passed to `emit`):

    route, plan    the Router's choice for planning; the plan as checked in code (workbench/planner.py)
    mission_start  request, outcome, plan_note, beats; and help -- what the workbench can do -- when nothing runs
    beat_start     index, id, kind, title, caption, agents, planned_by
      ...          the beat's own events: run_start, stage_enter, stage, evidence, decision,
                   route, summary, run_end (inspection); library (search); route, task,
                   attempt_start, attempt, code_result (code); route, reply (reply);
                   agent and tool throughout
    beat_end       index, id, outcome, seconds
    mission_end    outcome, seconds, outcomes
"""

from __future__ import annotations

import time
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from workbench import chat, coder, coding_tasks, planner, router, sandbox, tools
from workbench.run_inspection import JobConfig, run_job

ROOT = Path(__file__).resolve().parent.parent

Emit = Callable[[dict], None]

BEAT_FIELDS = ("id", "kind", "title", "caption", "agents", "planned_by")


def _inspection(beat: dict, emit: Emit) -> str:
    cfg = JobConfig(doc_id=beat["doc_id"], source=beat.get("source", "scan"),
                    scan_quality=beat.get("scan_quality", "medium"),
                    image=[ROOT / p for p in beat["image"]] if beat.get("image") else None,
                    inject_fault=beat.get("inject_fault"),
                    pause_for_review=beat.get("pause_for_review", False))
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
    decision = router.route("code", {"beat": beat["id"], "coding_task": task.task_id})
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


def _reply(beat: dict, emit: Emit) -> str:
    r = chat.reply(beat["question"], emit=emit)
    emit({"type": "reply", "question": beat["question"], "outcome": r.outcome, "text": r.text, "label": r.label,
          "model": r.model})
    return r.outcome


BEATS = {"inspection": _inspection, "library": _library, "code": _code, "reply": _reply}


def settings_for(step: dict, settings: dict | None) -> dict:
    """The caller's settings for a step's kind, with any `by_<arg>` entry matching the step's own arguments."""
    kind = (settings or {}).get(step["kind"]) or {}
    out = {k: v for k, v in kind.items() if not k.startswith("by_")}
    for arg, value in step["args"].items():
        out.update(((kind.get(f"by_{arg}") or {}).get(value)) or {})
    return out


def beats_from_plan(plan: planner.Plan, settings: dict | None = None) -> list[dict]:
    """A beat for each checked step: its arguments, the caller's settings for it, and who planned it.
    A `caption` in the settings is shown after the Planner's own reason for the step."""
    beats = []
    for i, step in enumerate(plan.steps, 1):
        extra = settings_for(step, settings)
        caption = " ".join(c for c in (step["why"], extra.pop("caption", "")) if c)
        beats.append({**extra, **step["args"], "id": f"step{i}", "kind": step["kind"], "title": step["title"],
                      "caption": caption, "agents": step["agents"], "planned_by": "planner"})
    return beats


def run_beats(beats: list[dict], emit: Emit) -> list[dict]:
    outcomes = []
    for i, beat in enumerate(beats):
        emit({"type": "beat_start", "index": i, **{k: beat.get(k) for k in BEAT_FIELDS}})
        t = time.monotonic()
        outcome = BEATS[beat["kind"]](beat, emit)
        outcomes.append({"id": beat["id"], "outcome": outcome})
        emit({"type": "beat_end", "index": i, "id": beat["id"], "outcome": outcome,
              "seconds": round(time.monotonic() - t, 1)})
    return outcomes


def run(request: str, emit: Emit, settings: dict | None = None, history: list | None = None) -> dict:
    """Plan `request` (with the chat's earlier turns), then run what was planned.
    Nothing runs unless the plan passed its checks; then the person is told what can be asked for."""
    started = time.monotonic()
    p = planner.plan(request, emit=emit, history=history)
    beats = beats_from_plan(p, settings)
    emit({"type": "mission_start", "request": request, "outcome": p.outcome, "plan_note": p.text,
          "beats": [{k: b.get(k) for k in BEAT_FIELDS} for b in beats],
          **({} if beats else {"help": planner.capabilities()})})
    outcomes = run_beats(beats, emit)
    seconds = round(time.monotonic() - started, 1)
    emit({"type": "mission_end", "outcome": p.outcome, "seconds": seconds, "outcomes": outcomes})
    return {"plan": p.outcome, "seconds": seconds, "outcomes": outcomes}
