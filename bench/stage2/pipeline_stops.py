"""When the pipeline stops for a person, was it right to? When it finishes, is the outcome right?

    .venv\\Scripts\\python bench\\stage2\\pipeline_stops.py --quality heavy
    .venv\\Scripts\\python bench\\stage2\\pipeline_stops.py --quality medium --out results\\stage2\\stops_medium.json

The reader scorer measures values. This measures DECISIONS, which is what a
refinery actually cares about. For every corpus report at one scan quality it
runs the real pipeline (`workbench.run_inspection --no-model`, one after
another -- the runs share a hash-chained audit log) and sorts the result:

    reached a note  ->  is the outcome the one in index.json?
    stopped         ->  RIGHT STOP if at least one critical value was genuinely
                        wrong or missing; FALSE ALARM if every flagged value
                        was in fact read correctly.

A false alarm costs a person a look at a correct value. A wrong outcome on a
finished note is the failure the whole design exists to prevent -- the script
exits 1 if there is one.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from workbench import rules  # noqa: E402
from workbench.evidence import CORPUS  # noqa: E402
from workbench.scan_reader import from_corpus  # noqa: E402

NUMERIC = ("nominal_mm", "previous_mm", "current_mm", "min_required_mm")


def run_pipeline(doc_id: str, quality: str) -> tuple[str, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "workbench.run_inspection", doc_id, "--source", "scan",
         "--scan-quality", quality, "--no-model"],
        capture_output=True, text=True, cwd=str(ROOT))
    lines = proc.stdout.splitlines()
    ended = next((l.split(":", 1)[1].strip() for l in lines if l.startswith("ended at:")), "crashed")
    fails = [l.strip() for l in lines if "[FAIL]" in l]
    return ended, fails[-1] if fails else ""


def classify_stop(doc_id: str, quality: str) -> dict:
    """Which flagged critical values were really wrong, and which were right."""
    truth = json.loads((CORPUS / "truth" / f"{doc_id}.json").read_text(encoding="utf-8"))
    ev = from_corpus(doc_id, quality)
    readings = {r["cml_id"]: r for r in truth["readings"]}
    findings = {f["finding_id"]: f for f in truth["findings"]}
    genuine, false = [], []
    for r in ev.readings:
        if r.review_status != "needs review":
            continue
        for f in NUMERIC:
            if not any(p.startswith(f"{r.cml_id}.{f}") for p in ev.problems):
                continue
            got, want = getattr(r, f), readings.get(r.cml_id, {}).get(f)
            wrong = got is None or want is None or Decimal(str(got)) != Decimal(str(want))
            (genuine if wrong else false).append(f"{r.cml_id}.{f}: read {got}, printed {want}")
    for f in ev.findings:
        if f.severity not in rules.GRADES:
            genuine.append(f"{f.finding_id}.severity: read {f.severity!r}, "
                           f"printed {findings.get(f.finding_id, {}).get('severity')!r}")
    missing_rows = sorted(set(readings) - {r.cml_id for r in ev.readings})
    if missing_rows:
        genuine.append(f"thickness rows not read: {', '.join(missing_rows)}")
    missing_findings = sorted(set(findings) - {f.finding_id for f in ev.findings})
    if missing_findings:
        genuine.append(f"findings not read: {', '.join(missing_findings)}")
    return {"verdict": "right stop" if genuine else "FALSE ALARM",
            "wrong_and_flagged": genuine, "right_but_flagged": false}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quality", required=True, choices=["clean", "light", "medium", "heavy"])
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    index = {e["doc_id"]: e for e in json.loads((CORPUS / "index.json").read_text(encoding="utf-8"))}
    results, counts = [], {"note_right": 0, "note_WRONG": 0, "right_stop": 0, "false_alarm": 0}
    print(f"pipeline on the {args.quality} scans, one report at a time\n")
    for doc_id in sorted(index):
        ended, why = run_pipeline(doc_id, args.quality)
        row = {"doc_id": doc_id, "ended": ended, "stopped_because": why}
        if ended == "done":
            decision = rules.evaluate(from_corpus(doc_id, args.quality))
            want = "ESCALATE" if index[doc_id]["requires_approval"] else "NO TRIGGER"
            row.update(outcome=decision.outcome, expected=want, correct=decision.outcome == want)
            counts["note_right" if row["correct"] else "note_WRONG"] += 1
            print(f"  {doc_id}  note      {decision.outcome:11} expected {want:11} "
                  f"{'correct' if row['correct'] else '<-- WRONG OUTCOME ON A FINISHED NOTE'}")
        else:
            row.update(classify_stop(doc_id, args.quality))
            counts["right_stop" if row["verdict"] == "right stop" else "false_alarm"] += 1
            print(f"  {doc_id}  stopped   {row['verdict']:11} {why.split('->')[-1].strip()[:90]}")
            for g in row["wrong_and_flagged"]:
                print(f"               wrong & flagged : {g}")
            for g in row["right_but_flagged"]:
                print(f"               right but flagged: {g}")
        results.append(row)

    print(f"\nnotes: {counts['note_right']} correct, {counts['note_WRONG']} WRONG   "
          f"stops: {counts['right_stop']} right, {counts['false_alarm']} false alarm(s)")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"quality": args.quality, "counts": counts, "reports": results},
                                       indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"written: {args.out}")
    return 1 if counts["note_WRONG"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
