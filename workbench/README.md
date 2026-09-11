# Inspection workbench

Turns an inspection report into a **draft approval note** in Word, where code
decides, the model only explains, and every value can be traced to its source.

```powershell
.venv\Scripts\python -m workbench.run_inspection insp_1002                        # the trap case
.venv\Scripts\python -m workbench.run_inspection insp_1002 --inject-fault render  # show self-healing
.venv\Scripts\python -m workbench.run_inspection insp_1003 --no-model             # no model at all
```

The note lands in `runs/<job-id>/05_render_note/`. Every stage's output is in
the same run folder, and every step is logged in `logs/workbench_runs.jsonl`
(hash-chained; check it with `python -m mcp_servers.audit logs\workbench_runs.jsonl`).

## What happens, in order

The order is set by the procedural graph `graphs/inspection.yaml`, and the
runner (`procedural_graph.py`) enforces it.

| Stage | Who | What it does |
|---|---|---|
| read_document | code | Finds the page images. *OCR is not built yet.* |
| build_evidence | code | One evidence record per finding and per thickness reading (`evidence.py`). *For now built from the corpus's ground-truth file, and every note says so.* |
| apply_rules | **code only** | THK-01 (thickness below minimum), SEV-01 (Major/Critical finding), EVD-01 (missing value) → ESCALATE, NO TRIGGER or NEEDS REVIEW (`rules.py`). Exact decimals. |
| write_summary | model | Writes one summary paragraph. Code checks it: every number must be in the evidence, any claim that a reading is below minimum must match the rules, no verdicts like "approved". One repair attempt, then a code-written summary (`prose.py`). |
| render_note | code | Fills the Word template: decision box, findings, thickness table with breaches in red, actions, blank sign-off, evidence appendix, verification record (`report_writer.py`). |
| qa_check | code | Reads the finished file back and compares every critical value with the evidence. A failure goes back to render_note (the self-healing loop); out of budget, it goes to a person. |

## Why the checks matter

On 2026-09-11 our best model (granite4.1:8b) wrote, for two of the twelve
test reports, that thickness readings were "below the minimum" when they were
well above it. The checker caught both. Giving the model the rules' status
for every reading, instead of letting it compare numbers, was the fix.

More: [`docs/HARNESS_AND_ROADMAP.md`](../docs/HARNESS_AND_ROADMAP.md).
