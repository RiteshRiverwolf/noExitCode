"""Run the inspection workflow for one report, through its procedural graph.

    .venv\\Scripts\\python -m workbench.run_inspection insp_1002
    .venv\\Scripts\\python -m workbench.run_inspection insp_1002 --inject-fault render
    .venv\\Scripts\\python -m workbench.run_inspection insp_1003 --no-model

Every stage writes its output into runs/<job-id>/<stage>/, the path taken is
saved as trace.json, and each step is appended to the hash-chained log
logs/workbench_runs.jsonl.

--inject-fault render makes the first rendering write a wrong thickness for
the breached CML. The QA check must catch it and send the work back to
render_note: a deliberate demonstration of the self-healing loop, labelled as
such in the trace.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from mcp_servers.audit import LOG_DIR, AuditLog
from workbench import evidence as evidence_mod
from workbench import prose, report_writer, rules
from workbench.procedural_graph import Graph, StageResult, run

ROOT = Path(__file__).resolve().parent.parent
GRAPH = Path(__file__).resolve().parent / "graphs" / "inspection.yaml"


def _save(folder: Path, name: str, data) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    text = data if isinstance(data, str) else json.dumps(data, indent=2, ensure_ascii=False, default=str)
    (folder / name).write_text(text, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("doc_id")
    ap.add_argument("--model", default=prose.DEFAULT_MODEL)
    ap.add_argument("--no-model", action="store_true", help="write the summary with code only")
    ap.add_argument("--scan-quality", default="medium", choices=["clean", "light", "medium", "heavy"])
    ap.add_argument("--inject-fault", choices=["render"], default=None)
    args = ap.parse_args()

    graph = Graph.load(GRAPH)
    job = f"{args.doc_id}-{datetime.now():%Y%m%d-%H%M%S}"
    folder = ROOT / "runs" / job
    audit = AuditLog("workbench", LOG_DIR / "workbench_runs.jsonl")
    ctx: dict = {"doc_id": args.doc_id, "trace": []}
    run_info = {"run_id": job, "generated_at": datetime.now().strftime("%d %b %Y %H:%M"),
                "graph": f"{graph.name} v{graph.version} ({GRAPH.relative_to(ROOT).as_posix()})",
                "trace": ctx["trace"]}
    note_path = folder / "05_render_note" / f"approval_note_{args.doc_id}.docx"

    def read_document(c):
        idx = {e["doc_id"]: e for e in json.loads((evidence_mod.CORPUS / "index.json").read_text())}
        pages = idx[c["doc_id"]]["scans"][args.scan_quality]
        _save(folder / "01_read_document", "pages.json", pages)
        return StageResult("ok", f"{len(pages)} page image(s); OCR not built yet -- stand-in below")

    def build_evidence(c):
        ev = evidence_mod.from_ground_truth(c["doc_id"], args.scan_quality)
        gaps = [r.cml_id for r in ev.readings if r.current_mm is None or r.min_required_mm is None]
        c["evidence"] = ev
        _save(folder / "02_build_evidence", "evidence.json", ev.to_json())
        if gaps:
            return StageResult("fail", f"missing values for {', '.join(gaps)}")
        return StageResult("ok", f"{len(ev.findings)} findings, {len(ev.readings)} readings "
                                 f"(ground-truth stand-in)")

    def apply_rules(c):
        d = rules.evaluate(c["evidence"])
        c["decision"] = d
        _save(folder / "03_apply_rules", "decision.json", asdict(d))
        fired = ", ".join(f"{t.rule_id}:{t.subject}" for t in d.triggers) or "none"
        return StageResult("ok", f"{d.outcome}; triggered: {fired}")

    def write_summary(c):
        s = prose.write_summary(c["evidence"], c["decision"], None if args.no_model else args.model,
                                guidance=c["guidance"])
        c["summary"] = s
        _save(folder / "04_write_summary", "summary.json", asdict(s))
        tries = len(s.attempts)
        if s.written_by.startswith("code (fallback"):
            return StageResult("ok", f"model failed checks {tries}x; code summary used")
        if s.attempts and s.attempts[-1].get("accepted_with_style_issue"):
            return StageResult("ok", f"{s.written_by}; accurate, accepted on attempt {tries} "
                                     f"despite style: {s.attempts[-1]['accepted_with_style_issue'][0]}")
        return StageResult("ok", f"{s.written_by}; passed checks on attempt {max(tries, 1)}")

    def render_note(c):
        corrupt = args.inject_fault == "render" and c["attempt"] == 1
        report_writer.render(c["evidence"], c["decision"], c["summary"], run_info, note_path, corrupt=corrupt)
        return StageResult("ok", "written" + (" (INJECTED FAULT: wrong value on purpose)" if corrupt else ""))

    def qa_check(c):
        results = report_writer.verify(note_path, c["evidence"], c["decision"])
        failed = [n for n, ok, _ in results if not ok]
        _save(folder / "06_qa_check", "verification.json", results)
        if failed:
            return StageResult("fail", f"{len(failed)} check(s) failed: {failed[0]}")
        # Stamp the passed checks into the note itself, then read it back once more.
        report_writer.render(c["evidence"], c["decision"], c["summary"], run_info, note_path, qa_results=results)
        again = report_writer.verify(note_path, c["evidence"], c["decision"])
        if not all(ok for _, ok, _ in again):
            return StageResult("fail", "final file failed its read-back")
        return StageResult("ok", f"all {len(results)} read-back checks passed")

    def on_step(step):
        ctx["trace"].append(step)
        audit.write({"event": "stage", "run_id": job, **asdict(step)})
        mark = "ok  " if step.status == "ok" else "FAIL"
        print(f"  [{mark}] {step.node:15} attempt {step.attempt}  {step.seconds:>6}s  -> {step.next:13} {step.note}")

    print(f"run {job}  (graph {graph.name} v{graph.version})")
    audit.write({"event": "run_start", "run_id": job, "doc_id": args.doc_id,
                 "model": None if args.no_model else args.model, "inject_fault": args.inject_fault})
    handlers = {"read_document": read_document, "build_evidence": build_evidence, "apply_rules": apply_rules,
                "write_summary": write_summary, "render_note": render_note, "qa_check": qa_check}
    result = run(graph, handlers, ctx, on_step)

    _save(folder, "trace.json", [asdict(s) for s in result.trace])
    audit.write({"event": "run_end", "run_id": job, "end": result.end,
                 "note": note_path.relative_to(ROOT).as_posix() if note_path.exists() else None})
    print(f"\nended at: {result.end}")
    if note_path.exists():
        print(f"note: {note_path}")
    if "summary" in ctx:
        print(f"\nsummary ({ctx['summary'].written_by}):\n{ctx['summary'].text}")
    return 0 if result.end == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
