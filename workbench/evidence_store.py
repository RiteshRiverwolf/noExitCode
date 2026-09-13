"""The evidence store: every reading and finding the Reader has taken, exact and structured.

    .venv\\Scripts\\python -m workbench.evidence_store ingest            # every corpus report, from its PDF
    .venv\\Scripts\\python -m workbench.evidence_store ingest --quality heavy
    .venv\\Scripts\\python -m workbench.evidence_store below-minimum
    .venv\\Scripts\\python -m workbench.evidence_store equipment R-2247
    .venv\\Scripts\\python -m workbench.evidence_store grew

One of the knowledge base's two stores (docs/WHOLE_PICTURE.md section 7a). It is
a plain SQL database, not a vector index, because it answers questions whose
answers are numbers: "what was CML-03?", "which readings are below their
minimum?", "every Major finding on R-2247". The other store -- the reference
library, for wording and citations -- never supplies a number.

What it keeps, and why:
  * every value as the exact string it was read as ("12.32", never 12.32 as a
    float), compared with Decimal -- the same rule as the rules engine;
  * where each value came from: file, page, box, OCR score, how it was read,
    the crop -- so an answer built on the store can still be shown on the page;
  * the reader's own verdict on each row. A row marked "needs review" is kept,
    and every query leaves it out by default and says how many it left out. An
    agent can therefore never quietly compute over a value a person has not
    confirmed.

Queries return plain dicts with their provenance attached; snapshot() exports
the whole store as JSON for code running in the sandbox, which has no access to
this machine and so cannot open the database itself.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from mcp_servers.audit import LOG_DIR, AuditLog
from workbench.evidence import EvidenceSet

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "evidence" / "evidence.sqlite"
NEEDS_REVIEW = "needs review"

SCHEMA = """
create table if not exists reports (
    doc_id text primary key,
    report_no text, equipment_tag text, equipment_name text, unit text, plant text,
    inspection_type text, inspection_date text, inspection_date_iso text, next_due_date text,
    inspector_name text, corrosion_rate_mm_yr text, remaining_life_yr text,
    extraction text, source_files text, evidence_sha256 text,
    problems integer, ingested_at text, run_id text
);
create table if not exists readings (
    doc_id text not null, cml_id text not null, location text,
    nominal_mm text, previous_mm text, current_mm text, min_required_mm text,
    review_status text, printed_status text,
    page integer, bbox text, score real, read_by text, source_file text, crop text,
    primary key (doc_id, cml_id)
);
create table if not exists findings (
    doc_id text not null, finding_id text not null, severity text, location text,
    description text, ref_clause text, recommendation text,
    page integer, read_by text, source_file text,
    primary key (doc_id, finding_id)
);
create index if not exists readings_doc on readings(doc_id);
create index if not exists findings_doc on findings(doc_id);
create index if not exists reports_tag on reports(equipment_tag);
"""

_AUDIT: AuditLog | None = None


def _audit() -> AuditLog:
    global _AUDIT
    if _AUDIT is None:
        _AUDIT = AuditLog("evidence_store", LOG_DIR / "evidence_store.jsonl")
    return _AUDIT


def connect(path: Path = DB) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def _s(v) -> str | None:
    return None if v is None else str(v)


def _dec(v) -> Decimal | None:
    try:
        return None if v in (None, "") else Decimal(str(v))
    except InvalidOperation:
        return None


def _iso(date_text: str | None) -> str | None:
    """'03-02-2026' -> '2026-02-03', so reports sort by date. Unparseable stays None."""
    try:
        return datetime.strptime(str(date_text), "%d-%m-%Y").date().isoformat()
    except (TypeError, ValueError):
        return None


# --- writing ------------------------------------------------------------------

def ingest(ev: EvidenceSet, run_id: str | None = None, con: sqlite3.Connection | None = None) -> dict:
    """Store one report's evidence, replacing any earlier reading of the same report."""
    own = con is None
    con = con or connect()
    h = ev.header
    with con:
        for table in ("readings", "findings", "reports"):
            con.execute(f"delete from {table} where doc_id = ?", (ev.doc_id,))
        con.execute(
            "insert into reports values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ev.doc_id, _s(h.get("report_no")), _s(h.get("equipment_tag")), _s(h.get("equipment_name")),
             _s(h.get("unit")), _s(h.get("plant")), _s(h.get("inspection_type")),
             _s(h.get("inspection_date")), _iso(h.get("inspection_date")), _s(h.get("next_due_date")),
             _s(h.get("inspector_name")), _s(h.get("corrosion_rate_mm_yr")), _s(h.get("remaining_life_yr")),
             ev.extraction, json.dumps(ev.source_files), ev.sha256(), len(ev.problems),
             datetime.now(timezone.utc).isoformat(timespec="seconds"), run_id))
        for r in ev.readings:
            con.execute(
                "insert into readings values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ev.doc_id, r.cml_id, r.location, _s(r.nominal_mm), _s(r.previous_mm), _s(r.current_mm),
                 _s(r.min_required_mm), r.review_status, r.printed_status, r.source.page,
                 json.dumps(r.source.bbox) if r.source.bbox else None, r.source.score,
                 r.source.read_by, r.source.file, r.source.crop))
        for f in ev.findings:
            con.execute(
                "insert into findings values (?,?,?,?,?,?,?,?,?,?)",
                (ev.doc_id, f.finding_id, f.severity, f.location, f.description, f.ref_clause,
                 f.recommendation, f.source.page, f.source.read_by, f.source.file))
    held = sum(1 for r in ev.readings if r.review_status == NEEDS_REVIEW)
    record = {"event": "ingest", "doc_id": ev.doc_id, "readings": len(ev.readings),
              "findings": len(ev.findings), "awaiting_review": held,
              "evidence_sha256": ev.sha256(), "run_id": run_id}
    _audit().write(record)
    if own:
        con.close()
    return record


# --- reading --------------------------------------------------------------------

def _provenance(row: sqlite3.Row) -> dict:
    return {"file": row["source_file"], "page": row["page"], "read_by": row["read_by"]}


def _readings(con: sqlite3.Connection, include_unreviewed: bool) -> tuple[list[sqlite3.Row], int]:
    rows = con.execute(
        "select r.*, p.report_no, p.equipment_tag, p.inspection_date, p.inspection_date_iso "
        "from readings r join reports p using (doc_id) order by p.equipment_tag, r.cml_id").fetchall()
    held = [r for r in rows if r["review_status"] == NEEDS_REVIEW]
    return (rows if include_unreviewed else [r for r in rows if r["review_status"] != NEEDS_REVIEW]), len(held)


def reports(con: sqlite3.Connection | None = None) -> list[dict]:
    con = con or connect()
    return [dict(r) for r in con.execute("select * from reports order by equipment_tag, inspection_date_iso")]


def below_minimum(include_unreviewed: bool = False, con: sqlite3.Connection | None = None) -> dict:
    """Every reading below its minimum, worst shortfall first."""
    con = con or connect()
    rows, held = _readings(con, include_unreviewed)
    out = []
    for r in rows:
        cur, mn = _dec(r["current_mm"]), _dec(r["min_required_mm"])
        if cur is None or mn is None or not cur < mn:
            continue
        out.append({"equipment_tag": r["equipment_tag"], "report_no": r["report_no"], "doc_id": r["doc_id"],
                    "cml_id": r["cml_id"], "location": r["location"], "current_mm": r["current_mm"],
                    "min_required_mm": r["min_required_mm"], "shortfall_mm": str(mn - cur),
                    "source": _provenance(r)})
    out.sort(key=lambda x: (-Decimal(x["shortfall_mm"]), x["equipment_tag"] or "", x["cml_id"]))
    return {"rows": out, "left_out_awaiting_review": 0 if include_unreviewed else held}


def thickness_grew(include_unreviewed: bool = False, con: sqlite3.Connection | None = None) -> dict:
    """Readings thicker now than at the previous inspection.

    Metal does not grow back. Either the reading is wrong, or the component was
    repaired or replaced and the record should say so -- a person decides which.
    """
    con = con or connect()
    rows, held = _readings(con, include_unreviewed)
    out = []
    for r in rows:
        cur, prev = _dec(r["current_mm"]), _dec(r["previous_mm"])
        if cur is not None and prev is not None and cur > prev:
            out.append({"equipment_tag": r["equipment_tag"], "report_no": r["report_no"], "doc_id": r["doc_id"],
                        "cml_id": r["cml_id"], "previous_mm": r["previous_mm"], "current_mm": r["current_mm"],
                        "grew_by_mm": str(cur - prev), "source": _provenance(r)})
    return {"rows": out, "left_out_awaiting_review": 0 if include_unreviewed else held}


def equipment(tag: str, con: sqlite3.Connection | None = None) -> dict:
    """Everything recorded for one equipment tag, oldest report first."""
    con = con or connect()
    reps = [dict(r) for r in con.execute(
        "select * from reports where upper(equipment_tag) = upper(?) order by inspection_date_iso", (tag,))]
    for rep in reps:
        rep["readings"] = [dict(r) for r in con.execute(
            "select * from readings where doc_id = ? order by cml_id", (rep["doc_id"],))]
        rep["findings"] = [dict(f) for f in con.execute(
            "select * from findings where doc_id = ? order by finding_id", (rep["doc_id"],))]
    return {"equipment_tag": tag, "reports": reps}


def findings(severity: str | None = None, tag: str | None = None, clause: str | None = None,
             con: sqlite3.Connection | None = None) -> list[dict]:
    con = con or connect()
    sql = ("select f.*, p.report_no, p.equipment_tag, p.inspection_date from findings f "
           "join reports p using (doc_id) where 1=1")
    args: list = []
    if severity:
        sql += " and lower(f.severity) = lower(?)"
        args.append(severity)
    if tag:
        sql += " and upper(p.equipment_tag) = upper(?)"
        args.append(tag)
    if clause:
        # Clause ids compared without spaces or punctuation: "API 510 Cl. 7.2" = "API510 Cl 7.2".
        sql += " and replace(replace(replace(lower(f.ref_clause),' ',''),'.',''),',','') like ?"
        args.append("%" + "".join(ch for ch in clause.lower() if ch.isalnum()) + "%")
    return [dict(r) for r in con.execute(sql + " order by p.equipment_tag, f.finding_id", args)]


def snapshot(include_unreviewed: bool = False, con: sqlite3.Connection | None = None) -> dict:
    """The whole store as plain JSON, for code in the sandbox.

    Values stay exact strings. Unreviewed readings are left out unless asked
    for, and the snapshot says how many.
    """
    con = con or connect()
    rows, held = _readings(con, include_unreviewed)
    keep = ("doc_id", "report_no", "equipment_tag", "inspection_date", "cml_id", "location",
            "nominal_mm", "previous_mm", "current_mm", "min_required_mm", "review_status")
    return {
        "note": "values are exact strings as read; convert with decimal.Decimal, not float",
        "reports": [{k: r[k] for k in ("doc_id", "report_no", "equipment_tag", "equipment_name", "unit",
                                        "inspection_type", "inspection_date", "next_due_date",
                                        "corrosion_rate_mm_yr", "remaining_life_yr")} for r in reports(con)],
        "readings": [{k: r[k] for k in keep} for r in rows],
        "findings": [{k: f[k] for k in ("doc_id", "report_no", "equipment_tag", "finding_id", "severity",
                                         "location", "description", "ref_clause", "recommendation")}
                     for f in findings(con=con)],
        "left_out_awaiting_review": 0 if include_unreviewed else held,
    }


# --- command line ------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ing = sub.add_parser("ingest", help="read every corpus report and store its evidence")
    ing.add_argument("--quality", choices=["clean", "light", "medium", "heavy"], default=None,
                     help="read the scans at this quality (default: the born-digital PDFs)")
    sub.add_parser("reports")
    bm = sub.add_parser("below-minimum")
    bm.add_argument("--include-unreviewed", action="store_true")
    sub.add_parser("grew")
    eq = sub.add_parser("equipment")
    eq.add_argument("tag")
    fd = sub.add_parser("findings")
    fd.add_argument("--severity")
    fd.add_argument("--tag")
    fd.add_argument("--clause")
    args = ap.parse_args()

    if args.cmd == "ingest":
        from workbench.evidence import CORPUS
        from workbench.scan_reader import from_corpus
        con = connect()
        for entry in json.loads((CORPUS / "index.json").read_text(encoding="utf-8")):
            ev = from_corpus(entry["doc_id"], args.quality, ROOT / "runs" / "_evidence_store")
            rec = ingest(ev, con=con)
            print(f"{rec['doc_id']}: {rec['readings']} readings, {rec['findings']} findings, "
                  f"{rec['awaiting_review']} awaiting review")
        con.close()
        return 0
    result = {"reports": lambda: reports(),
              "below-minimum": lambda: below_minimum(args.include_unreviewed),
              "grew": lambda: thickness_grew(),
              "equipment": lambda: equipment(args.tag),
              "findings": lambda: findings(args.severity, args.tag, args.clause)}[args.cmd]()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
