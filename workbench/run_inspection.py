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
from workbench import pagesource, prose, report_writer, router, rules, scan_reader
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
    ap.add_argument("--model", default=None,
                    help="override the Router's choice for the summary (recorded as an override)")
    ap.add_argument("--no-model", action="store_true", help="write the summary with code only")
    ap.add_argument("--scan-quality", default="medium", choices=["clean", "light", "medium", "heavy"])
    ap.add_argument("--image", nargs="+", type=Path, default=None,
                    help="read these files instead of the corpus: one PDF, or the page "
                         "images of one report in order")
    ap.add_argument("--source", default="scan", choices=["scan", "pdf", "stand-in"],
                    help="scan: read the scan images by OCR (default); pdf: read the "
                         "born-digital PDF's own text; stand-in: the old ground-truth "
                         "shortcut, kept only for comparison")
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
        """The document itself: its own text where it has one, OCR where it does not."""
        if args.source == "stand-in":
            idx = {e["doc_id"]: e for e in json.loads((evidence_mod.CORPUS / "index.json").read_text())}
            pages = idx[c["doc_id"]]["scans"][args.scan_quality]
            _save(folder / "01_read_document", "pages.json", pages)
            return StageResult("ok", f"{len(pages)} page image(s); evidence comes from the "
                                     f"ground-truth stand-in, not from these")
        work = folder / "01_read_document" / "pages"
        if args.image:
            pages = (pagesource.open_document(args.image[0], work)
                     if args.image[0].suffix.lower() == ".pdf"
                     else pagesource.open_pages(args.image, work))
        else:
            quality = None if args.source == "pdf" else args.scan_quality
            pages = scan_reader.corpus_pages(c["doc_id"], quality, work)
        c["pages"] = pages
        _save(folder / "01_read_document", "pages.json",
              [{"page": p.number, "file": p.source_file, "read_by": p.read_by,
                "texts": len(p.items), "size": [p.width, p.height]} for p in pages])
        empty = [p.number for p in pages if not p.items]
        if empty:
            return StageResult("fail", f"no text read from page(s) {empty}")
        how = ", ".join(sorted({p.read_by.split(" (")[0] for p in pages}))
        return StageResult("ok", f"{len(pages)} page(s), {sum(len(p.items) for p in pages)} "
                                 f"pieces of text, read by {how}")

    def build_evidence(c):
        """Evidence records, and the decision to stop when a critical value is doubtful."""
        if args.source == "stand-in":
            ev = evidence_mod.from_ground_truth(c["doc_id"], args.scan_quality)
        else:
            ev = scan_reader.build_evidence(c["doc_id"], c["pages"],
                                            crop_dir=folder / "02_build_evidence" / "crops")
        c["evidence"] = ev
        _save(folder / "02_build_evidence", "evidence.json", ev.to_json())
        if ev.problems:
            _save(folder / "02_build_evidence", "problems.json",
                  {"problems": ev.problems, "notes": ev.notes})
        # Only a doubt about a value a decision is made from stops the run. A
        # low-confidence location is recorded on the note; a thickness that may
        # be missing a digit is not something to carry forward.
        doubtful = [r.cml_id for r in ev.readings if r.review_status == "needs review"]
        if doubtful:
            return StageResult("fail", f"thickness values need a person: {', '.join(doubtful)}")
        # An unread grade is not a Minor one: a "Major" that OCR left empty would
        # silently drop an escalation (insp_1010's medium scan, 2026-09-13).
        ungraded = [f.finding_id for f in ev.findings if f.severity not in rules.GRADES]
        if ungraded:
            return StageResult("fail", f"severity not readable, which could hide an escalation: "
                                       f"{', '.join(ungraded)}")
        if not ev.readings or not ev.findings:
            return StageResult("fail", "the findings or thickness table was not read")
        extra = f" ({len(ev.problems)} problem(s) recorded)" if ev.problems else ""
        return StageResult("ok", f"{len(ev.findings)} findings, {len(ev.readings)} readings{extra}")

    def apply_rules(c):
        d = rules.evaluate(c["evidence"])
        c["decision"] = d
        _save(folder / "03_apply_rules", "decision.json", asdict(d))
        fired = ", ".join(f"{t.rule_id}:{t.subject}" for t in d.triggers) or "none"
        return StageResult("ok", f"{d.outcome}; triggered: {fired}")

    def write_summary(c):
        # The Router picks the model from measured results and logs why; --model
        # overrides it, and the override is recorded as one.
        model, routed = None, "no model: --no-model"
        if not args.no_model:
            if args.model:
                model, routed = args.model, f"{args.model}, set by hand (Router overridden)"
            else:
                d = router.route("write_summary", {"run_id": job, "stage": "write_summary"})
                model = d.chosen
                routed = (f"Router chose {d.chosen}" if d.chosen
                          else f"Router found no qualified model ({d.reason}); code writes it")
            c["routing"] = {"task": "write_summary", "model": model, "decision": routed}
            _save(folder / "04_write_summary", "routing.json", c["routing"])
        s = prose.write_summary(c["evidence"], c["decision"], model, guidance=c["guidance"])
        c["summary"] = s
        _save(folder / "04_write_summary", "summary.json", asdict(s))
        tries = len(s.attempts)
        if s.written_by.startswith("code (fallback"):
            return StageResult("ok", f"{routed}; model failed checks {tries}x; code summary used")
        if s.attempts and s.attempts[-1].get("accepted_with_style_issue"):
            return StageResult("ok", f"{routed}; accurate, accepted on attempt {tries} "
                                     f"despite style: {s.attempts[-1]['accepted_with_style_issue'][0]}")
        return StageResult("ok", f"{routed}; {s.written_by} passed checks on attempt {max(tries, 1)}")

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
                 "model": "none (--no-model)" if args.no_model else (args.model or "chosen by the Router"),
                 "inject_fault": args.inject_fault})
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
