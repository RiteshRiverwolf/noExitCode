"""The pitch demo: one mission, several agents, every beat a real run.

    POST /api/demo      (workbench/server.py) -- runs it as a job, events streamed live
    .venv\\Scripts\\python -m workbench.demo      -- the same run, printed

The Planner plans the scenario's request (workbench/planner.py) and code checks
the plan; the steps then run as any mission's do (workbench/missions.py). The
scenario -- workbench/demo.yaml, the one thing fixed -- supplies only what a plan
cannot know (which scan, the fault injected on purpose) and the beats no plan
would contain (a damaged copy of the same report), each labelled as the
scenario's. When no plan can be made, the scenario's own beats run instead,
labelled with the reason.

Events, in order (each a dict passed to `emit`):

    route, plan  the Router's choice for planning; the plan as checked in code
    demo_start   title, request, plan_note, beats (each with planned_by: planner | scenario)
    router       the Router's choice and every candidate's reason, per task
    beat_start   index, id, kind, title, caption, agents, planned_by
      ...        the beat's own events (workbench/missions.py)
    beat_end     index, id, outcome, seconds
    demo_end     seconds
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

import yaml

from workbench import missions, planner, router

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


def plan_beats(p: planner.Plan, s: dict) -> tuple[list[dict], str]:
    """The beats the demo runs, and the note shown with the plan.

    Planned: the Planner's checked steps with the scenario's settings, and each
    `staged` beat placed after the last planned step of the kind it names in
    `after` (at the end when there is none). Not planned: the scenario's own
    beats, and why the Planner did not plan."""
    if p.outcome != "planned":
        return ([{**b, "planned_by": "scenario"} for b in s["beats"]],
                s["plan_notes"]["scenario"].replace("{reason}", p.text))
    beats = missions.beats_from_plan(p, s.get("step_settings"))
    for staged in (b for b in s["beats"] if b.get("staged")):
        after = [i for i, b in enumerate(beats) if b["kind"] == staged.get("after")]
        beats.insert(after[-1] + 1 if after else len(beats), {**staged, "planned_by": "scenario"})
    return beats, s["plan_notes"]["planned"].replace("{plan}", p.text)


def run(emit: Emit) -> dict:
    s = scenario()
    started = time.monotonic()
    p = planner.plan(s["request"], emit=emit)
    beats, note = plan_beats(p, s)
    emit({"type": "demo_start", "title": s["title"], "request": s["request"], "plan_note": note,
          "beats": [{k: b.get(k) for k in missions.BEAT_FIELDS} for b in beats]})
    emit({"type": "router", "tasks": router_view(s["router_tasks"])})
    outcomes = missions.run_beats(beats, emit)
    seconds = round(time.monotonic() - started, 1)
    emit({"type": "demo_end", "seconds": seconds, "outcomes": outcomes})
    return {"plan": p.outcome, "seconds": seconds, "outcomes": outcomes}


def main() -> int:
    def show(e: dict) -> None:
        kind = e["type"]
        if kind in ("demo_start", "beat_start", "beat_end", "demo_end", "notice", "route", "decision"):
            print(json.dumps({k: v for k, v in e.items() if k not in ("beats", "caption")}, default=str)[:220])
        elif kind == "plan":
            print(f"plan [{e['outcome']}] {e['model']}: {e['text']}")
            for i, step in enumerate(e["steps"], 1):
                print(f"    {i}. {step['title']}  -- {step['why']}")
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
