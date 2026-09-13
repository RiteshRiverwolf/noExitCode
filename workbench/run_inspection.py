"""Run the inspection workflow for one report, through its procedural graph.

    .venv\\Scripts\\python -m workbench.run_inspection insp_1002
    .venv\\Scripts\\python -m workbench.run_inspection insp_1002 --inject-fault render
    .venv\\Scripts\\python -m workbench.run_inspection insp_1003 --no-model

Or from code -- what the local service behind the interface calls:

    from workbench.run_inspection import JobConfig, run_job
    run_job(JobConfig("insp_1002", source="pdf"), emit=print)

Every stage writes its output into runs/<job-id>/<stage>/, the path taken is
saved as trace.json, and each step is appended to the hash-chained log
logs/workbench_runs.jsonl.

`emit` receives one plain dict per event, in order -- run_start, stage_enter,
stage, route, evidence, decision, summary, run_end -- so a live view shows what
the agents are doing as they do it. The events carry the same facts the run
folder does; nothing is shown on screen that is not also on disk.

Stopping for a person. When a critical value stays doubtful the graph goes to
review_values. With `pause_for_review` (the service sets it) the run pauses
there: a `review` event lists every doubtful value with its crop, run_end
reports end "paused", and the run waits in memory. A person's decision -- the
values read from the original report, or "remeasure" -- is checked by
check_review; claim_review takes the run and continue_run resumes it from
exactly that step. Entered values are recorded with the engineer's name and
what the scan had read, and the rules, the note and the read-back run on them.
Without `pause_for_review` (the command line) nobody is asked, and the run ends
at needs_review.

--inject-fault render makes the first rendering write a wrong thickness for
the breached CML. The QA check must catch it and send the work back to
render_note: a deliberate demonstration of the self-healing loop, labelled as
such in the trace.
"""

from __future__ import annotations

import argparse
import importlib
import json
import re
import threading
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Callable

import yaml

from mcp_servers.audit import LOG_DIR, AuditLog
from workbench import evidence as evidence_mod
from workbench import prose, router, rules, tools
from workbench.procedural_graph import Graph, StageResult
from workbench.scan_reader import THICKNESS_TABLE

ROOT = Path(__file__).resolve().parent.parent
GRAPH = Path(__file__).resolve().parent / "graphs" / "inspection.yaml"
ORCHESTRATION = Path(__file__).resolve().parent / "orchestration.yaml"
ENGINES = {"langgraph": "workbench.graph_engine", "procedural_graph": "workbench.procedural_graph"}
FIELD_LABELS = {"nominal_mm": "nominal thickness", "previous_mm": "previous thickness",
                "current_mm": "current thickness", "min_required_mm": "minimum required thickness"}
AS_PRINTED = re.compile(r"\d+(?:\.\d+)?")        # a thickness typed from the original: digits, one decimal point


def engine_run(name: str | None) -> tuple[str, Callable]:
    """The runner named in orchestration.yaml, or `name` when given. Imported on use."""
    name = name or yaml.safe_load(ORCHESTRATION.read_text(encoding="utf-8"))["engine"]
    if name not in ENGINES:
        raise ValueError(f"unknown engine {name!r}; known: {', '.join(ENGINES)}")
    return name, importlib.import_module(ENGINES[name]).run


_AUDIT: AuditLog | None = None
_AUDIT_LOCK = threading.Lock()


def _audit() -> AuditLog:
    """One log writer per process. Two AuditLog objects appending to the same file
    would each keep their own idea of the last hash and fork the chain."""
    global _AUDIT
    with _AUDIT_LOCK:
        if _AUDIT is None:
            _AUDIT = AuditLog("workbench", LOG_DIR / "workbench_runs.jsonl")
        return _AUDIT


@dataclass
class JobConfig:
    doc_id: str
    source: str = "scan"                 # scan | pdf | stand-in
    scan_quality: str = "medium"
    image: list[Path] | None = None      # any PDF, or the page images of one report
    model: str | None = None             # overrides the Router, and is logged as an override
    no_model: bool = False
    inject_fault: str | None = None
    engine: str | None = None            # the graph runner; None: the one orchestration.yaml names
    pause_for_review: bool = False       # wait at review_values for a person (needs the langgraph engine)


def _save(folder: Path, name: str, data) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    text = data if isinstance(data, str) else json.dumps(data, indent=2, ensure_ascii=False, default=str)
    (folder / name).write_text(text, encoding="utf-8")


def _exact(v) -> str | None:
    """Decimals travel as the exact printed string -- never as a float."""
    return None if v is None else str(v)


def _evidence_event(ev: evidence_mod.EvidenceSet) -> dict:
    return {
        "type": "evidence",
        "extraction": ev.extraction,
        "readings": [{
            "cml_id": r.cml_id, "location": r.location,
            "nominal_mm": _exact(r.nominal_mm), "previous_mm": _exact(r.previous_mm),
            "current_mm": _exact(r.current_mm), "min_required_mm": _exact(r.min_required_mm),
            "review_status": r.review_status, "printed_status": r.printed_status,
            "page": r.source.page, "bbox": r.source.bbox, "score": r.source.score,
            "read_by": r.source.read_by, "crop": r.source.crop,
        } for r in ev.readings],
        "findings": [{
            "finding_id": f.finding_id, "severity": f.severity, "location": f.location,
            "description": f.description, "ref_clause": f.ref_clause,
            "recommendation": f.recommendation, "page": f.source.page, "crop": f.source.crop,
        } for f in ev.findings],
        "problems": ev.problems, "notes": ev.notes, "pages": ev.pages, "reviewed": ev.reviewed,
    }


# --- stopping for a person ---------------------------------------------------------------

def evidence_gate(ev: evidence_mod.EvidenceSet) -> str | None:
    """Why this evidence may not go to the rules, or None.

    Only a doubt about a value a decision is made from stops the run. A
    low-confidence location is recorded on the note; a thickness that may be
    missing a digit is not something to carry forward. An unread grade is not a
    Minor one: a "Major" that OCR left empty would silently drop an escalation
    (insp_1010's medium scan, 2026-09-13).
    """
    doubtful = [r.cml_id for r in ev.readings if r.review_status == "needs review"]
    if doubtful:
        return f"thickness values need a person: {', '.join(doubtful)}"
    ungraded = [f.finding_id for f in ev.findings if f.severity not in rules.GRADES]
    if ungraded:
        return f"severity not readable, which could hide an escalation: {', '.join(ungraded)}"
    if not ev.readings or not ev.findings:
        return "the findings or thickness table was not read"
    return None


def _column_decimals(ev: evidence_mod.EvidenceSet, field: str) -> int | None:
    """How many decimals a thickness column prints, from the rows nobody doubts."""
    counts = Counter(-getattr(r, field).as_tuple().exponent for r in ev.readings
                     if r.review_status != "needs review" and getattr(r, field) is not None)
    return counts.most_common(1)[0][0] if counts else None


def review_request(run_id: str, ev: evidence_mod.EvidenceSet, reason: str) -> dict | None:
    """What a person is asked: every doubtful value, with its crop and why. None when no entry could resolve it."""
    items = []
    for r in ev.readings:
        if r.review_status != "needs review":
            continue
        doubted = [f for f in THICKNESS_TABLE.numeric
                   if getattr(r, f) is None or any(p.startswith(f"{r.cml_id}.{f}:") for p in ev.problems)]
        for f in doubted or ["current_mm"]:
            items.append({
                "field": f"{r.cml_id}.{f}", "kind": "thickness",
                "label": f"{r.cml_id} · {FIELD_LABELS.get(f, f)}", "location": r.location,
                "read_as": _exact(getattr(r, f)), "decimals": _column_decimals(ev, f),
                "min_required_mm": _exact(r.min_required_mm),
                "crop": r.source.crop if f == "current_mm" else None,
                "page": r.source.page, "bbox": r.source.bbox, "score": r.source.score,
                "why": [p.split(": ", 1)[1] for p in ev.problems if p.startswith(f"{r.cml_id}.{f}:")]})
    for f in ev.findings:
        if f.severity in rules.GRADES:
            continue
        items.append({
            "field": f"{f.finding_id}.severity", "kind": "grade",
            "label": f"{f.finding_id} · severity grade", "location": f.location,
            "read_as": f.severity or None, "options": sorted(rules.GRADES),
            "crop": f.source.crop, "page": f.source.page, "bbox": f.source.bbox, "score": f.source.score,
            "why": [p.split(": ", 1)[1] for p in ev.problems
                    if p.startswith((f"{f.finding_id}:", f"{f.finding_id}.severity:"))]})
    if not items:
        return None
    return {"run_id": run_id, "doc_id": ev.doc_id, "reason": reason, "items": items}


def check_review(request: dict, decision) -> list[str]:
    """Problems with a person's decision; empty when it may resume the run. Nothing is rounded or repaired."""
    if not isinstance(decision, dict):
        return ["send the decision as a JSON object"]
    problems = []
    if not str(decision.get("reviewer") or "").strip():
        problems.append("enter your name: every value a person enters is recorded against their name")
    action = decision.get("action")
    if action == "remeasure":
        return problems
    if action != "confirm":
        return problems + ["action must be 'confirm' or 'remeasure'"]
    values = decision.get("values")
    if not isinstance(values, dict):
        return problems + ["values: one entry per value under review"]
    unknown = sorted(set(values) - {i["field"] for i in request["items"]})
    if unknown:
        problems.append(f"not under review: {', '.join(unknown)}")
    for item in request["items"]:
        v = str(values.get(item["field"]) or "").strip()
        places = len(v.partition(".")[2])
        if not v:
            problems.append(f"{item['label']}: enter the value as printed on the original report")
        elif item["kind"] == "grade":
            if v not in item["options"]:
                problems.append(f"{item['label']}: {v!r} is not one of the report's grades "
                                f"({', '.join(item['options'])})")
        elif not AS_PRINTED.fullmatch(v):
            problems.append(f"{item['label']}: {v!r} is not a number as printed (digits and one decimal point)")
        elif item.get("decimals") is not None and places != item["decimals"]:
            problems.append(f"{item['label']}: this column prints {item['decimals']} decimal(s); "
                            f"{v!r} has {places}")
    return problems


def apply_review(ev: evidence_mod.EvidenceSet, request: dict, decision: dict) -> list[dict]:
    """Put a person's entries into the evidence, each recorded with who entered it and what the scan read."""
    reviewer = str(decision["reviewer"]).strip()
    readings = {r.cml_id: r for r in ev.readings}
    findings = {f.finding_id: f for f in ev.findings}
    entered = []
    for item in request["items"]:
        subject, field = item["field"].rsplit(".", 1)
        value = str(decision["values"][item["field"]]).strip()
        if item["kind"] == "grade":
            target = findings[subject]
            target.severity = value
        else:
            target = readings[subject]
            setattr(target, field, Decimal(value))
        target.method += f"; {field} entered by {reviewer} from the original report"
        entered.append({"field": item["field"], "entered": value, "read_as": item["read_as"],
                        "reviewer": reviewer})
    for r in ev.readings:
        if r.review_status == "needs review" and any(e["field"].startswith(f"{r.cml_id}.") for e in entered):
            r.review_status = f"entered by {reviewer}"
    ev.reviewed.extend(entered)
    return entered


@dataclass
class PausedRun:
    run_id: str
    doc_id: str
    request: dict                                   # what the person was asked (the review event)
    resume: Callable[[dict, Callable[[dict], None] | None], dict]
    paused_at: float


class ReviewRefused(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


_PAUSED: dict[str, PausedRun] = {}
_PAUSED_LOCK = threading.Lock()


def paused_runs() -> list[dict]:
    """Runs waiting for a person in this process (they do not survive a restart)."""
    with _PAUSED_LOCK:
        return [{"run_id": p.run_id, "doc_id": p.doc_id, "paused_at": p.paused_at, "request": p.request}
                for p in _PAUSED.values()]


def claim_review(run_id: str, decision) -> PausedRun:
    """Take a paused run for a person's decision: checked first, and taken only once.
    Raises KeyError for no such paused run, ReviewRefused when the decision fails its checks."""
    with _PAUSED_LOCK:
        paused = _PAUSED.get(run_id)
        if paused is None:
            raise KeyError(run_id)
        problems = check_review(paused.request, decision)
        if problems:
            raise ReviewRefused(problems)
        return _PAUSED.pop(run_id)


def continue_run(paused: PausedRun, decision: dict, emit: Callable[[dict], None] | None = None) -> dict:
    """Resume a claimed run from its review step; its events go to `emit`."""
    return paused.resume(decision, emit)


# --- the run ---------------------------------------------------------------------------------

def run_job(cfg: JobConfig, emit: Callable[[dict], None] | None = None) -> dict:
    """Run one report through the graph. Returns where it ended -- "paused" while it waits for
    a person -- and what it produced."""

    sink = {"emit": emit}                  # a resumed run reports to whoever resumed it

    def send(event: dict) -> None:
        target = sink["emit"]
        if target is None:
            return
        try:
            target(event)
        except Exception:  # a broken viewer must never break the run it is watching
            pass

    graph = Graph.load(GRAPH)
    engine, run = engine_run(cfg.engine)
    if cfg.pause_for_review and engine != "langgraph":
        raise ValueError("pausing for a person needs the langgraph engine (workbench/orchestration.yaml)")
    stamp = f"{cfg.doc_id}-{datetime.now():%Y%m%d-%H%M%S}"
    job, n = stamp, 1
    while (ROOT / "runs" / job).exists():      # two runs of one report in the same second
        n += 1
        job = f"{stamp}-{n}"
    folder = ROOT / "runs" / job
    folder.mkdir(parents=True, exist_ok=True)
    audit = _audit()
    ctx: dict = {"doc_id": cfg.doc_id, "trace": []}
    run_info = {"run_id": job, "generated_at": datetime.now().strftime("%d %b %Y %H:%M"),
                "graph": f"{graph.name} v{graph.version} ({GRAPH.relative_to(ROOT).as_posix()})",
                "trace": ctx["trace"]}
    note_path = folder / "05_render_note" / f"approval_note_{cfg.doc_id}.docx"
    execution = None

    def read_document(c):
        """The document itself: its own text where it has one, OCR where it does not."""
        if cfg.source == "stand-in":
            idx = {e["doc_id"]: e for e in json.loads((evidence_mod.CORPUS / "index.json").read_text())}
            pages = idx[c["doc_id"]]["scans"][cfg.scan_quality]
            _save(folder / "01_read_document", "pages.json", pages)
            return StageResult("ok", f"{len(pages)} page image(s); evidence comes from the "
                                     f"ground-truth stand-in, not from these")
        work = folder / "01_read_document" / "pages"
        pages = tools.call("read_pages", work_dir=work, doc_id=c["doc_id"], files=cfg.image,
                           quality=None if cfg.source == "pdf" else cfg.scan_quality)
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
        if cfg.source == "stand-in":
            ev = tools.call("ground_truth_stand_in", doc_id=c["doc_id"], scan_quality=cfg.scan_quality)
        else:
            ev = tools.call("build_evidence", doc_id=c["doc_id"], pages=c["pages"],
                            crop_dir=folder / "02_build_evidence" / "crops")
        c["evidence"] = ev
        _save(folder / "02_build_evidence", "evidence.json", ev.to_json())
        if ev.problems:
            _save(folder / "02_build_evidence", "problems.json",
                  {"problems": ev.problems, "notes": ev.notes})
        send(_evidence_event(ev))
        stop = evidence_gate(ev)
        if stop:
            c["stop_reason"] = stop
            c["review_request"] = review_request(job, ev, stop)
            return StageResult("fail", stop)
        extra = f" ({len(ev.problems)} problem(s) recorded)" if ev.problems else ""
        return StageResult("ok", f"{len(ev.findings)} findings, {len(ev.readings)} readings{extra}")

    def review_values(c):
        """A person's entries in place of doubtful values -- or, where nobody can be asked, a clean stop."""
        request, decision = c.get("review_request"), c.pop("review_decision", None)
        reason = c.get("stop_reason", "")
        if request is None:
            return StageResult("fail", f"nothing a person can enter resolves this: {reason}")
        if decision is None:
            return StageResult("fail", f"no one to ask in this run; {reason}")
        reviewer = str(decision.get("reviewer") or "").strip()
        if decision.get("action") == "remeasure":
            return StageResult("fail", f"sent for re-measurement by {reviewer}; {reason}")
        problems = check_review(request, decision)
        if problems:
            return StageResult("fail", "; ".join(problems))
        entered = apply_review(c["evidence"], request, decision)
        c["review_request"] = None
        _save(folder / "02b_review_values", "review.json",
              {"reviewer": reviewer, "entered": entered, "asked": request})
        _save(folder / "02b_review_values", "evidence.json", c["evidence"].to_json())
        send(_evidence_event(c["evidence"]))
        still = evidence_gate(c["evidence"])
        if still:
            return StageResult("fail", f"after the entries by {reviewer}: {still}")
        return StageResult("ok", f"{len(entered)} value(s) entered by {reviewer} from the original report: "
                                 + ", ".join(f"{e['field']} = {e['entered']}" for e in entered))

    def apply_rules(c):
        d = tools.call("apply_rules", ev=c["evidence"])
        c["decision"] = d
        _save(folder / "03_apply_rules", "decision.json", asdict(d))
        send({"type": "decision", "outcome": d.outcome, "ruleset": d.ruleset_version,
              "triggers": [{"rule_id": t.rule_id, "subject": t.subject, "detail": t.detail,
                            "title": t.title, "action": t.action} for t in d.triggers],
              "review_items": [{"rule_id": t.rule_id, "subject": t.subject, "detail": t.detail}
                               for t in d.review_items]})
        fired = ", ".join(f"{t.rule_id}:{t.subject}" for t in d.triggers) or "none"
        return StageResult("ok", f"{d.outcome}; triggered: {fired}")

    def write_summary(c):
        # The Router picks the model from measured results and logs why; --model
        # overrides it, and the override is recorded as one.
        model, routed = None, "no model: --no-model"
        if not cfg.no_model:
            if cfg.model:
                model, routed = cfg.model, f"{cfg.model}, set by hand (Router overridden)"
            else:
                d = router.route("write_summary", {"run_id": job, "stage": "write_summary"})
                model = d.chosen
                routed = (f"Router chose {d.chosen}" if d.chosen
                          else f"Router found no qualified model ({d.reason}); code writes it")
            c["routing"] = {"task": "write_summary", "model": model, "decision": routed}
            _save(folder / "04_write_summary", "routing.json", c["routing"])
            send({"type": "route", "task": "write_summary", "chosen": model, "decision": routed})
        s = prose.write_summary(c["evidence"], c["decision"], model, guidance=c["guidance"])
        c["summary"] = s
        _save(folder / "04_write_summary", "summary.json", asdict(s))
        send({"type": "summary", "text": s.text, "written_by": s.written_by, "attempts": len(s.attempts)})
        tries = len(s.attempts)
        if s.written_by.startswith("code (fallback"):
            return StageResult("ok", f"{routed}; model failed checks {tries}x; code summary used")
        if s.attempts and s.attempts[-1].get("accepted_with_style_issue"):
            return StageResult("ok", f"{routed}; accurate, accepted on attempt {tries} "
                                     f"despite style: {s.attempts[-1]['accepted_with_style_issue'][0]}")
        return StageResult("ok", f"{routed}; {s.written_by} passed checks on attempt {max(tries, 1)}")

    def render_note(c):
        corrupt = cfg.inject_fault == "render" and c["attempt"] == 1
        tools.call("write_note", ev=c["evidence"], decision=c["decision"], summary=c["summary"], run=run_info,
                   out=note_path, corrupt=corrupt)
        return StageResult("ok", "written" + (" (INJECTED FAULT: wrong value on purpose)" if corrupt else ""))

    def qa_check(c):
        results = tools.call("read_back_note", path=note_path, ev=c["evidence"], decision=c["decision"])
        failed = [n for n, ok, _ in results if not ok]
        _save(folder / "06_qa_check", "verification.json", results)
        if failed:
            return StageResult("fail", f"{len(failed)} check(s) failed: {failed[0]}")
        # Stamp the passed checks into the note itself, then read it back once more.
        tools.call("stamp_note", ev=c["evidence"], decision=c["decision"], summary=c["summary"], run=run_info,
                   out=note_path, qa_results=results)
        again = tools.call("read_back_note", path=note_path, ev=c["evidence"], decision=c["decision"])
        if not all(ok for _, ok, _ in again):
            return StageResult("fail", "final file failed its read-back")
        return StageResult("ok", f"all {len(results)} read-back checks passed")

    def as_agent(agent_id: str, node: str, stage: Callable[[dict], StageResult]) -> Callable[[dict], StageResult]:
        """A stage runs as the agent the graph names for it: only that agent's tools, its lifecycle logged."""
        def handler(c: dict) -> StageResult:
            with tools.acting(agent_id, send, run_id=job, node=node, attempt=c["attempt"]) as act:
                outcome = stage(c)
                if outcome.status != "ok":
                    act.fail(outcome.note)
                return outcome
        return handler

    def on_enter(node: str, agent: str, attempt: int) -> None:
        send({"type": "stage_enter", "run_id": job, "node": node, "agent": agent, "attempt": attempt})

    def on_step(step):
        ctx["trace"].append(step)
        audit.write({"event": "stage", "run_id": job, **asdict(step)})
        send({"type": "stage", "run_id": job, **asdict(step),
              "next_kind": graph.nodes[step.next]["kind"] if step.next in graph.nodes else "end"})

    def finish(result) -> dict:
        _save(folder, "trace.json", [asdict(s) for s in result.trace])
        note = note_path.relative_to(ROOT).as_posix() if note_path.exists() else None
        summary = ctx.get("summary")
        outcome = {"run_id": job, "end": result.end, "note": note,
                   "folder": folder.relative_to(ROOT).as_posix(),
                   "summary_text": summary.text if summary else None,
                   "written_by": summary.written_by if summary else None,
                   "reason": None if result.end == "done"
                   else next((s.note for s in reversed(result.trace) if s.status != "ok"), None)}
        if result.end == "paused":
            request = ctx["review_request"]
            with _PAUSED_LOCK:
                _PAUSED[job] = PausedRun(job, cfg.doc_id, request, resume, time.time())
            audit.write({"event": "run_paused", "run_id": job, "at": execution.paused_at,
                         "asked": [i["field"] for i in request["items"]]})
            send({"type": "review", **request})
        else:
            audit.write({"event": "run_end", "run_id": job, "end": result.end, "note": note})
        send({"type": "run_end", **outcome})
        return outcome

    def resume(decision: dict, new_emit: Callable[[dict], None] | None) -> dict:
        sink["emit"] = new_emit
        reviewer = str(decision.get("reviewer") or "").strip()
        audit.write({"event": "run_resume", "run_id": job, "action": decision.get("action"),
                     "reviewer": reviewer, "values": decision.get("values") or {}})
        send({"type": "run_resumed", "run_id": job, "doc_id": cfg.doc_id, "graph": f"{graph.name} v{graph.version}",
              "engine": engine, "action": decision.get("action"), "reviewer": reviewer,
              "values": decision.get("values") or {}})
        return finish(execution.resume(decision))

    model_label = "none (--no-model)" if cfg.no_model else (cfg.model or "chosen by the Router")
    send({"type": "run_start", "run_id": job, "doc_id": cfg.doc_id,
          "graph": f"{graph.name} v{graph.version}", "engine": engine, "source": cfg.source,
          "scan_quality": cfg.scan_quality, "image": [str(p) for p in cfg.image or []],
          "model": model_label, "inject_fault": cfg.inject_fault, "pause_for_review": cfg.pause_for_review,
          "folder": folder.relative_to(ROOT).as_posix()})
    audit.write({"event": "run_start", "run_id": job, "doc_id": cfg.doc_id, "engine": engine,
                 "model": model_label, "inject_fault": cfg.inject_fault})
    stages = {"read_document": read_document, "build_evidence": build_evidence, "review_values": review_values,
              "apply_rules": apply_rules, "write_summary": write_summary, "render_note": render_note,
              "qa_check": qa_check}
    handlers = {node: as_agent(graph.nodes[node]["agent_id"], node, fn) for node, fn in stages.items()}
    if engine == "langgraph":
        execution = importlib.import_module(ENGINES[engine]).Execution(
            graph, handlers, ctx, on_step, on_enter, pause_at_review=cfg.pause_for_review)
        result = execution.start()
    else:
        result = run(graph, handlers, ctx, on_step, on_enter)
    return finish(result)


def _console(event: dict) -> None:
    """The command line's view of a run: the same lines it has always printed,
    which bench/stage2/pipeline_stops.py and the severity test read."""
    if event["type"] == "run_start":
        print(f"run {event['run_id']}  (graph {event['graph']})")
    elif event["type"] == "stage":
        mark = "ok  " if event["status"] == "ok" else "FAIL"
        print(f"  [{mark}] {event['node']:15} attempt {event['attempt']}  {event['seconds']:>6}s  "
              f"-> {event['next']:13} {event['note']}")


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
    ap.add_argument("--engine", choices=sorted(ENGINES), default=None,
                    help="the graph runner (default: the one workbench/orchestration.yaml names)")
    args = ap.parse_args()

    cfg = JobConfig(doc_id=args.doc_id, source=args.source, scan_quality=args.scan_quality,
                    image=args.image, model=args.model, no_model=args.no_model,
                    inject_fault=args.inject_fault, engine=args.engine)
    outcome = run_job(cfg, emit=_console)
    print(f"\nended at: {outcome['end']}")
    if outcome["note"]:
        print(f"note: {ROOT / outcome['note']}")
    if outcome["summary_text"] is not None:
        print(f"\nsummary ({outcome['written_by']}):\n{outcome['summary_text']}")
    return 0 if outcome["end"] == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
