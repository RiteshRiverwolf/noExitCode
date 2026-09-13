"""A finding whose severity could not be read must never let a run finish quietly.

    .venv\\Scripts\\python bench\\stage2\\unreadable_severity_test.py

Found 2026-09-13 while scoring the 12 medium scans: OCR left insp_1010's F-03
severity ("Major") empty. The reader flagged it, but nothing acted on the flag:
the pipeline only stopped for doubtful thickness values, and the rules treated
an empty grade as simply "not Major or Critical". The run finished with a note.
It escalated anyway, but only because a thickness reading also breached. On a
report whose ONLY trigger is a Major finding, the same misread gives NO TRIGGER.

Two defences are tested, because either one alone could be bypassed later:
  1. the rules: an unrecognised grade is an EVD-01 review item, so the outcome
     can never be NO TRIGGER while a grade is missing;
  2. the pipeline: build_evidence stops the run before the rules are reached.

This test was run before the rules were fixed, and failed as it should: with
every escalating grade blanked the unfixed rules returned NO TRIGGER, a garbled
"Majr" returned NO TRIGGER, and a blanked grade beside a readable Major was not
listed for review. The pipeline half was written after the build_evidence gate
went in; before that gate, the same insp_1010 scan was observed to run to "done".
"""

from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from workbench import rules  # noqa: E402
from workbench.evidence import from_ground_truth  # noqa: E402

failures: list[str] = []


def expect(name: str, ok: bool, detail: str) -> None:
    print(f"  {'pass' if ok else 'FAIL'}  {name}: {detail}")
    if not ok:
        failures.append(name)


# --- 1. the rules, on a report whose only trigger is severity ------------------
print("rules -- insp_1000 escalates on severity alone")
ev = from_ground_truth("insp_1000")
base = rules.evaluate(ev)
expect("baseline", base.outcome == "ESCALATE" and all(t.rule_id == "SEV-01" for t in base.triggers),
       f"{base.outcome}, triggers {[f'{t.rule_id}:{t.subject}' for t in base.triggers]}")

escalating = [f.finding_id for f in ev.findings if f.severity in rules.ESCALATING_SEVERITIES]

blank_all = copy.deepcopy(ev)
for f in blank_all.findings:
    if f.severity in rules.ESCALATING_SEVERITIES:
        f.severity = ""
d = rules.evaluate(blank_all)
expect("every escalating grade unreadable", d.outcome != "NO TRIGGER",
       f"{d.outcome} (was NO TRIGGER before the fix); review items "
       f"{[r.subject for r in d.review_items]}")

if len(escalating) > 1:
    blank_one = copy.deepcopy(ev)
    next(f for f in blank_one.findings if f.finding_id == escalating[0]).severity = ""
    d = rules.evaluate(blank_one)
    expect("one of several escalating grades unreadable",
           d.outcome == "ESCALATE" and any(r.subject == escalating[0] for r in d.review_items),
           f"{d.outcome}; the unreadable one is listed for review: "
           f"{[r.subject for r in d.review_items]}")

garbled = copy.deepcopy(ev)
for f in garbled.findings:
    if f.severity in rules.ESCALATING_SEVERITIES:
        f.severity = "Majr"            # OCR damage: not a grade, and must not pass as one
d = rules.evaluate(garbled)
expect("a garbled grade", d.outcome != "NO TRIGGER", f"{d.outcome}")

# --- 2. the pipeline, on the real scan that exposed it -------------------------
print("\npipeline -- insp_1010 medium scan, where OCR left F-03's grade empty")
proc = subprocess.run(
    [sys.executable, "-m", "workbench.run_inspection", "insp_1010", "--source", "scan",
     "--scan-quality", "medium", "--no-model"],
    capture_output=True, text=True, cwd=str(ROOT))
ended = next((l.split(":", 1)[1].strip() for l in proc.stdout.splitlines()
              if l.startswith("ended at:")), "?")
stopped_at = [l.strip() for l in proc.stdout.splitlines() if "[FAIL] build_evidence" in l]
expect("the run does not finish", ended != "done", f"ended at {ended}")
expect("it stops at build_evidence, before the rules", bool(stopped_at),
       stopped_at[0] if stopped_at else "build_evidence never failed")

print(f"\n{'all checks passed' if not failures else f'{len(failures)} check(s) FAILED'}")
sys.exit(1 if failures else 0)
