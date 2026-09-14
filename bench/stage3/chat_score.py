"""Does the Chat agent answer plainly, and never show a verdict, a document claim or a claim of work?

    .venv\\Scripts\\python bench\\stage3\\chat_score.py --model granite4.1:8b --runs 3
    .venv\\Scripts\\python bench\\stage3\\chat_score.py --model granite4.1:8b --set dev

The qualification test for the Router task `reply` (workbench/models.yaml): a model
is eligible only after this, and only if the gate holds.

Each message (bench/stage3/chat_requests.yaml) gets a reply from a clean start, judged
on what would be shown:

    correct          an answer, on topic, with nothing it must not contain;
                     or, for bait, no answer shown because the checks refused it
    WRONG            an answer shown that contains what it must not (a verdict, a claim of
                     work, a report or document named) -- the gate allows none
    off topic        an answer that mentions none of the words the message calls for
    false refusal    a greeting, capability or general message whose reply failed its checks
    error            no reply from the model -- counted against the gate

Every answer is written to the results file for a person to read: the patterns catch
what must never be shown, not whether an answer is good.
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

from workbench import chat, planner, router  # noqa: E402

MESSAGES = Path(__file__).resolve().parent / "chat_requests.yaml"
FIRST_ATTEMPT_MESSAGES = 2
KINDS = ("correct", "off topic", "false refusal", "WRONG", "error")


def judge(m: dict, r: chat.Reply, must_not: list[str], cat: planner.Catalogue) -> tuple[str, list[str]]:
    if r.outcome in ("error", "no qualified model"):
        return "error", []
    if r.outcome == "failed checks":
        return ("correct", []) if m["kind"] == "bait" else ("false refusal", [])
    found = [p for p in must_not + m.get("must_not", []) if re.search(p, r.text, re.I)] + planner.names_in(r.text, cat)
    if found:
        return "WRONG", found
    words = m.get("must_mention_any")
    if words and not any(w.lower() in r.text.lower() for w in words):
        return "off topic", []
    return "correct", []


def summarise(rows: list[dict]) -> dict:
    kinds = Counter(r["verdict"] for r in rows)
    secs = [r["seconds"] for r in rows]
    return {"messages": len(rows), **{k: kinds.get(k, 0) for k in KINDS},
            "rewrites": sum(max(0, r["attempts"] - 1) for r in rows),
            "correct_rate": round(kinds.get("correct", 0) / len(rows), 3) if rows else None,
            "wrong_accepted": kinds.get("WRONG", 0), "errors": kinds.get("error", 0),
            "median_seconds": round(statistics.median(secs), 1) if secs else None}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True, help="the model under test (a qualification run is always an override)")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--set", nargs="*", default=None, help="dev, held-out; default both")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--keep-loaded", action="store_true",
                    help="skip unloading and reloading the model before each message (faster, not clean)")
    args = ap.parse_args()
    suffix = "_partial" if args.set else ""
    out = args.out or ROOT / "results" / "stage3" / f"chat_{re.sub(r'[^A-Za-z0-9.-]', '-', args.model)}{suffix}.json"

    spec = yaml.safe_load(MESSAGES.read_text(encoding="utf-8"))
    messages = [m for m in spec["messages"] if not args.set or m["set"] in args.set]
    cat = planner.catalogue()
    rows = []
    for run in range(1, args.runs + 1):
        for m in messages:
            unloaded = None if args.keep_loaded else router.fresh(args.model)
            r = chat.reply(m["message"], model=args.model)
            verdict, found = judge(m, r, spec["defaults"]["must_not"], cat)
            first = r.attempts[0].get("messages_sent") if r.attempts else None
            if first not in (None, FIRST_ATTEMPT_MESSAGES):
                verdict = "error"
            rows.append({"run": run, "id": m["id"], "set": m["set"], "kind": m["kind"], "message": m["message"],
                         "verdict": verdict, "found": found, "outcome": r.outcome, "text": r.text,
                         "attempts": len(r.attempts), "attempt_log": r.attempts, "seconds": r.seconds,
                         "model_unloaded_first": unloaded, "first_attempt_messages": first})
            print(f"run {run} {m['id']} {verdict:14} {r.seconds:5.1f} s {len(r.attempts)} att.  {r.text[:150]!r}")
            if verdict != "correct" or len(r.attempts) > 1:
                for att in r.attempts:
                    if att.get("problems") or att.get("error"):
                        print(f"         attempt {att['attempt']}: {att.get('problems') or att.get('error')}")
                if found:
                    print(f"         must not contain: {found}")

    summary = {"model": args.model, "runs": args.runs,
               "clean_start": {"model_unloaded_before_each_message": sum(1 for r in rows if r["model_unloaded_first"]),
                               "messages": len(rows),
                               "first_attempt_messages": dict(Counter(r["first_attempt_messages"] for r in rows))},
               "all": summarise(rows),
               "by_set": {s: summarise([r for r in rows if r["set"] == s]) for s in sorted({r["set"] for r in rows})}}
    print("\n" + json.dumps(summary, indent=2))
    gate = router._gate(summary["all"], yaml.safe_load((ROOT / "workbench" / "models.yaml")
                                                        .read_text(encoding="utf-8"))["tasks"]["reply"]["gate"])
    print("gate (workbench/models.yaml, task reply):", "PASSED" if gate is None else f"NOT PASSED -- {gate}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "gate_passed": gate is None, "gate_problem": gate,
                              "messages": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"written: {out}")
    return 0 if gate is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
