"""Does the Planner plan the right work, name the right report, and say what it cannot do?

    .venv\\Scripts\\python bench\\stage3\\planner_score.py --model granite4.1:8b --runs 3
    .venv\\Scripts\\python bench\\stage3\\planner_score.py --model granite4.1:8b --set dev
    .venv\\Scripts\\python bench\\stage3\\planner_score.py --model granite4.1:8b --only D01 H10

The qualification test for the Router task `plan` (workbench/models.yaml): a model
is eligible only after this, and only if the gate holds.

Each request (bench/stage3/planner_requests.yaml) is planned from a clean start and
judged on the plan code accepted -- the plan that would run:

    correct            the expected steps (kind and report or task; order and library
                       question not compared), and "not possible" said exactly when expected
    WRONG REPORT       a step reads a report the request does not ask for      } counted as
    WRONG TASK         a coding task nobody asked for                          } wrong_accepted:
    CLAIMED POSSIBLE   something no step can do, and the plan does not say so  } the gate allows none
    missing step / extra step / wrong not-possible note   an accepted plan, not the expected one
    refused by checks  the plan failed its checks twice; nothing would run, and the person is told
    error              no reply, or not JSON -- counted against the gate

Results are reported for all requests and per set: held-out requests are never
used to tune (see the request file).
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from workbench import planner, router  # noqa: E402

REQUESTS = Path(__file__).resolve().parent / "planner_requests.yaml"
FIRST_ATTEMPT_MESSAGES = 2      # instructions, and the request with the catalogue -- nothing earlier
GATE_KINDS = ("WRONG REPORT", "WRONG TASK", "CLAIMED POSSIBLE")
KINDS = ("correct", "missing step", "extra step", "wrong not-possible note", "refused by checks", *GATE_KINDS, "error")


def _key(kind: str, args: dict) -> tuple[str, str]:
    return kind, args.get("doc_id") or args.get("task_id") or ""


def judge(r: dict, p: planner.Plan) -> str:
    if p.outcome in ("error", "no qualified model"):
        return "error"
    if p.outcome == "failed checks":
        return "refused by checks"
    got = Counter(_key(s["kind"], s["args"]) for s in p.steps)
    wanted = [Counter((e[0], e[1] if len(e) > 1 else "") for e in steps)
              for steps in [r["expect"], *r.get("alternatives", [])]]
    want = next((w for w in wanted if w == got), wanted[0])    # an alternative counts only when it matches exactly
    extra, missing = got - want, want - got
    if any(k == "inspection" for k, _ in extra):
        return "WRONG REPORT"
    if any(k == "code" for k, _ in extra):
        return "WRONG TASK"
    if r["not_possible"] and not p.not_possible:
        return "CLAIMED POSSIBLE"
    if missing:
        return "missing step"
    if extra:
        return "extra step"
    if bool(p.not_possible) != r["not_possible"]:
        return "wrong not-possible note"
    return "correct"


def summarise(rows: list[dict]) -> dict:
    kinds = Counter(r["kind"] for r in rows)
    secs = [r["seconds"] for r in rows]
    return {"requests": len(rows), **{k: kinds.get(k, 0) for k in KINDS},
            "re_plans": sum(max(0, r["attempts"] - 1) for r in rows),
            "correct_rate": round(kinds.get("correct", 0) / len(rows), 3) if rows else None,
            "wrong_accepted": sum(kinds.get(k, 0) for k in GATE_KINDS),
            "errors": kinds.get("error", 0),
            "median_seconds": round(statistics.median(secs), 1) if secs else None}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True, help="the model under test (a qualification run is always an override)")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--set", nargs="*", default=None,
                    help="dev, held-out, dev-followup, held-out-followup; default all")
    ap.add_argument("--only", nargs="*", default=None, help="request ids, e.g. D01 H10")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--keep-loaded", action="store_true",
                    help="skip unloading and reloading the model before each request (faster, not clean)")
    args = ap.parse_args()
    suffix = "" if not (args.set or args.only) else "_partial"
    out = args.out or ROOT / "results" / "stage3" / f"planner_{re.sub(r'[^A-Za-z0-9.-]', '-', args.model)}{suffix}.json"

    requests = [r for r in yaml.safe_load(REQUESTS.read_text(encoding="utf-8"))["requests"]
                if (not args.set or r["set"] in args.set) and (not args.only or r["id"] in args.only)]
    rows = []
    for run in range(1, args.runs + 1):
        for r in requests:
            # A clean start for every request: the model is unloaded (confirmed) and reloaded with nothing cached.
            unloaded = None if args.keep_loaded else router.fresh(args.model)
            p = planner.plan(r["request"], model=args.model, history=r.get("history"))
            kind = judge(r, p)
            first = p.attempts[0].get("messages_sent") if p.attempts else None
            if first not in (None, FIRST_ATTEMPT_MESSAGES):
                kind = "error"
            planned = [list(_key(s["kind"], s["args"])) for s in p.steps]
            rows.append({"run": run, "id": r["id"], "set": r["set"], "request": r["request"],
                         "earlier_turns": len(p.history), "kind": kind,
                         "outcome": p.outcome, "planned": planned, "expected": r["expect"],
                         "not_possible": p.not_possible, "regulated_by": p.regulated_by,
                         "questions": [s["args"]["question"] for s in p.steps if "question" in s["args"]],
                         "attempts": len(p.attempts), "attempt_log": p.attempts, "seconds": p.seconds,
                         "model_unloaded_first": unloaded, "first_attempt_messages": first})
            print(f"run {run} {r['id']:4} {kind:24} {p.seconds:6.1f} s  {len(p.attempts)} att.  "
                  f"{planned}  {('NOT POSSIBLE: ' + p.not_possible) if p.not_possible else ''}"[:220])
            if kind != "correct":
                print(f"         expected {r['expect']} not_possible={r['not_possible']}")
                for att in p.attempts:
                    if att.get("problems") or att.get("error"):
                        print(f"         attempt {att['attempt']}: {att.get('problems') or att.get('error')}")

    summary = {"model": args.model, "runs": args.runs,
               "clean_start": {"model_unloaded_before_each_request": sum(1 for r in rows if r["model_unloaded_first"]),
                               "requests": len(rows),
                               "first_attempt_messages": dict(Counter(r["first_attempt_messages"] for r in rows))},
               "all": summarise(rows),
               "by_set": {s: summarise([r for r in rows if r["set"] == s]) for s in sorted({r["set"] for r in rows})}}
    print("\n" + json.dumps(summary, indent=2))
    gate = router._gate(summary["all"], yaml.safe_load((ROOT / "workbench" / "models.yaml")
                                                        .read_text(encoding="utf-8"))["tasks"]["plan"]["gate"])
    print("gate (workbench/models.yaml, task plan):", "PASSED" if gate is None else f"NOT PASSED -- {gate}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "gate_passed": gate is None, "gate_problem": gate,
                              "requests": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"written: {out}")
    return 0 if gate is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
