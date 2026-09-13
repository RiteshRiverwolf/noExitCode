"""Does the Librarian answer correctly, cite what it used, and refuse when it should?

    .venv\\Scripts\\python bench\\stage3\\librarian_score.py --model granite4.1:8b
    .venv\\Scripts\\python bench\\stage3\\librarian_score.py --model qwen3.5:9b --runs 2
    .venv\\Scripts\\python bench\\stage3\\librarian_score.py --model granite4.1:8b --only Q09 U02

The qualification test for the Router task answer_from_library
(workbench/models.yaml): a model is eligible only after this, and only if the
gate holds -- no accepted wrong answer and no invented answer, even once.

For each answerable question (bench/library/content.py, QUESTIONS):
    correct          answered, and every must_contain fact is in the answer
    MISSING FACT     answered and past the checks, but a must_contain fact is absent.
                     Counted against the gate, and printed in full for a person to
                     judge ("10%" for "10 percent" is normalised; other wordings only
                     where the question lists them)
    cited as expected  at least one citation is an expected section or page (reported,
                     not required: the same fact can be stated in two places)
    false refusal    said the library does not contain it, or failed its checks
For each unanswerable question:
    refused          correct -- "not in library" or "failed checks"
    ANSWERED         an answer got past the checks -- the gate allows none

Results are reported for all questions and separately per set: "held-out"
questions were written after a result was seen, and are never used to tune.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from bench.library.content import QUESTIONS  # noqa: E402
from workbench import router  # noqa: E402
from workbench.librarian import answer  # noqa: E402

FIRST_ATTEMPT_MESSAGES = 2      # instructions, and the question with its passages -- nothing earlier

GATE_KINDS = ("missing fact", "ANSWERED", "error")


def _plain(text: str) -> str:
    text = text.replace("%", " percent").replace(",", "")
    return re.sub(r"\s+", " ", text).strip().lower()


def absent_facts(q: dict, text: str) -> list:
    """must_contain entries not in the answer; an entry that is a list is any one of its wordings."""
    return [f for f in q["must_contain"]
            if not any(_plain(w) in _plain(text) for w in (f if isinstance(f, list) else [f]))]


def cited_as_expected(a, q) -> bool:
    by_label = {p["label"]: p for p in a.passages}
    cited = [by_label[l] for s in a.sentences for l in s["sources"] if l in by_label]
    return any((p["doc_id"], p["section"]) in {tuple(e) for e in q.get("expect", [])}
               or any(p["doc_id"] == d and p["pages"][0] <= pg <= p["pages"][1] for d, pg in q.get("expect_pages", []))
               for p in cited)


def judge(q: dict, a) -> tuple[str, str, dict]:
    """(kind, verdict line, extra fields) for one answer."""
    if a.outcome in ("error", "no qualified model"):
        return "error", a.outcome.upper(), {}
    if not q.get("answerable", True):
        return ("ANSWERED", "ANSWERED", {}) if a.outcome == "answered" else ("refused", f"refused ({a.outcome})", {})
    if a.outcome != "answered":
        return "false refusal", f"false refusal ({a.outcome})", {}
    absent, expected = absent_facts(q, a.text), cited_as_expected(a, q)
    extra = {"absent_facts": absent, "cited_as_expected": expected}
    if absent:
        return "missing fact", f"MISSING FACT {absent}", extra
    return "correct", "correct" + ("" if expected else " (cited elsewhere)"), extra


def summarise(rows: list[dict]) -> dict:
    kinds = Counter(r["kind"] for r in rows)
    answerable = sum(1 for r in rows if r["answerable"])
    secs = [r["seconds"] for r in rows]
    return {"questions": len(rows), "answerable": answerable, "unanswerable": len(rows) - answerable,
            **{k: kinds.get(k, 0) for k in ("correct", "missing fact", "false refusal", "refused", "ANSWERED", "error")},
            "cited_as_expected": sum(1 for r in rows if r.get("cited_as_expected")),
            "rewrites": sum(max(0, len(r["attempts"]) - 1) for r in rows),
            "correct_rate": round(kinds.get("correct", 0) / answerable, 3) if answerable else None,
            "accepted_wrong": kinds.get("missing fact", 0),
            "unanswerable_answered": kinds.get("ANSWERED", 0),
            "median_seconds": round(statistics.median(secs), 1) if secs else None}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True, help="the model under test (a qualification run is always an override)")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--only", nargs="*", default=None, help="question ids, e.g. Q09 U03")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--keep-loaded", action="store_true",
                    help="skip unloading and reloading the model before each question (faster, not clean)")
    args = ap.parse_args()
    out = args.out or ROOT / "results" / "stage3" / f"librarian_{re.sub(r'[^A-Za-z0-9.-]', '-', args.model)}.json"

    questions = [q for q in QUESTIONS if not args.only or q["id"] in args.only]
    rows = []
    for run in range(1, args.runs + 1):
        for q in questions:
            # A clean start for every question: the model is unloaded (confirmed) and reloaded
            # with nothing cached, before the timer starts.
            unloaded = None if args.keep_loaded else router.fresh(args.model)
            a = answer(q["question"], model=args.model)
            kind, verdict, extra = judge(q, a)
            first = a.attempts[0].get("messages_sent") if a.attempts else None
            if first not in (None, FIRST_ATTEMPT_MESSAGES):
                kind, verdict = "error", f"CONTEXT LEAK: first attempt sent {first} messages"
            rows.append({"run": run, "id": q["id"], "set": q.get("set", "main"),
                         "answerable": q.get("answerable", True), "question": q["question"],
                         "kind": kind, "verdict": verdict, "outcome": a.outcome, "text": a.text,
                         "seconds": a.seconds, "attempts": a.attempts, "model_unloaded_first": unloaded,
                         "first_attempt_messages": first,
                         "passages": [p["citation"] for p in a.passages], **extra})
            print(f"run {run} {q['id']}  {verdict:36} {a.seconds:6.1f} s  {len(a.attempts)} att.  {a.text[:140]}")
            if kind in GATE_KINDS or kind == "false refusal":
                for att in a.attempts:
                    print(f"         attempt {att.get('attempt')}: problems {att.get('problems', att.get('error'))}")
                    if kind != "false refusal":
                        print(f"         reply: {json.dumps(att.get('reply'), ensure_ascii=False)[:600]}")

    summary = {"model": args.model, "runs": args.runs,
               "clean_start": {"model_unloaded_before_each_question": sum(1 for r in rows if r["model_unloaded_first"]),
                               "questions": len(rows),
                               "first_attempt_messages": dict(Counter(r["first_attempt_messages"] for r in rows))},
               "all": summarise(rows),
               "by_set": {s: summarise([r for r in rows if r["set"] == s]) for s in sorted({r["set"] for r in rows})}}
    print("\n" + json.dumps(summary, indent=2))
    gate = all(summary["all"][k] == 0 for k in ("accepted_wrong", "unanswerable_answered", "error"))
    print("gate (no accepted wrong answer, no invented answer, no errors):", "PASSED" if gate else "NOT PASSED")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "gate_passed": gate, "questions": rows},
                              indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"written: {out}")
    return 0 if gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
