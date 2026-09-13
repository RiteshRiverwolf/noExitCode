"""Report Writer: fills the approval-note template from evidence and the rules' decision.

Code fills every fact, number and table from the evidence records. The model's
only contribution is the summary paragraph, which has already passed its
checks. The workbench never signs: the sign-off boxes are left blank for
people, and every page carries "DRAFT -- NOT AN APPROVAL".

`verify` reads the finished file back and compares its critical values with
the evidence (ARCHITECTURE section 7.3, artifact structure check).
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor

from workbench.evidence import STAND_IN, EvidenceSet
from workbench.prose import Summary
from workbench.rules import Decision

NAVY, GREY, INK, MUTED = "1F3A5F", "E7EAF0", "1B1F24", "5B6573"
OUTCOME_COLOURS = {            # (fill, text)
    "ESCALATE": ("FADBD8", "B42318"),
    "NEEDS REVIEW": ("FDEBC8", "B54708"),
    "NO TRIGGER": ("E4ECF5", NAVY),
}
SEVERITY_FILL = {"Critical": "F4C7C3", "Major": "FADBD8", "Minor": "FDF1D6", "Observation": "EEF2F6"}
BREACH_FILL, OK_TEXT, BREACH_TEXT = "FADBD8", "1E7A46", "B42318"
BANNER = "DRAFT FOR ENGINEERING REVIEW — NOT AN APPROVAL"
PLACEHOLDER = re.compile(r"\[(list|insert|add|enter|todo)[^\]]*\]|\{\{|\}\}", re.IGNORECASE)


# --- small helpers -------------------------------------------------------------------

def _shade(cell, fill: str) -> None:
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    cell._tc.get_or_add_tcPr().append(shd)


def _write(cell, text: str, bold=False, colour: str | None = None, size=8.5,
           align=None, italic=False) -> None:
    cell.text = ""
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(0)
    if align:
        p.alignment = align
    run = p.add_run(text)
    run.bold, run.italic = bold, italic
    run.font.size = Pt(size)
    run.font.color.rgb = RGBColor.from_string(colour or INK)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def _table(doc, widths_mm: list[float], header: list[str] | None = None):
    t = doc.add_table(rows=0, cols=len(widths_mm))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    if header:
        row = t.add_row().cells
        for c, h in zip(row, header):
            _write(c, h, bold=True, colour=NAVY)
            _shade(c, GREY)
    t._widths = widths_mm
    return t


def _row(t, values: list[str], **kw):
    cells = t.add_row().cells
    for c, v in zip(cells, values):
        _write(c, v, **kw)
    return cells


def _fix_widths(t) -> None:
    for row in t.rows:
        for c, w in zip(row.cells, t._widths):
            c.width = Mm(w)


def _heading(doc, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run(text.upper())
    r.bold = True
    r.font.size = Pt(10)
    r.font.color.rgb = RGBColor.from_string(NAVY)


def _para(doc, text: str, size=9.5, colour=INK, italic=False, bold=False, after=4):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(after)
    r = p.add_run(text)
    r.font.size, r.italic, r.bold = Pt(size), italic, bold
    r.font.color.rgb = RGBColor.from_string(colour)
    return p


def _kv(doc, pairs: list[tuple[str, str]], widths=(34, 56, 34, 50)):
    t = _table(doc, list(widths))
    for i in range(0, len(pairs), 2):
        chunk = pairs[i:i + 2] + [("", "")] * (2 - len(pairs[i:i + 2]))
        cells = t.add_row().cells
        for j, (k, v) in enumerate(chunk):
            _write(cells[2 * j], k, bold=True, colour=MUTED)
            _shade(cells[2 * j], "F5F7FA")
            _write(cells[2 * j + 1], v)
    _fix_widths(t)
    return t


def _mm(v: Decimal | None) -> str:
    return "—" if v is None else str(v)


# --- the note ----------------------------------------------------------------------------

def render(ev: EvidenceSet, decision: Decision, summary: Summary, run: dict, out: Path,
           qa_results: list[tuple[str, bool, str]] | None = None, corrupt: bool = False) -> Path:
    """Write the note. `corrupt` deliberately alters one value (fault-injection demo only)."""
    # A header field the reader could not find is written as exactly that -- never
    # as the word "None", and never a crash: report_no.split() below would fail on a
    # missing report number. (Found by reading this code on 2026-09-13, after a
    # missing Inspection Type crashed the summary on insp_1005 and insp_1008.)
    from workbench.prose import NOT_READ
    h = {k: (NOT_READ if v in (None, "") else v) for k, v in ev.header.items()}
    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name, normal.font.size = "Calibri", Pt(9.5)
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Mm(210), Mm(297)
    sec.left_margin = sec.right_margin = Mm(16)
    sec.top_margin, sec.bottom_margin = Mm(18), Mm(16)

    hp = sec.header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = hp.add_run(BANNER)
    r.bold, r.font.size = True, Pt(9)
    r.font.color.rgb = RGBColor.from_string(BREACH_TEXT)
    fp = sec.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = fp.add_run(f"Drafted by the SIH26117 inspection workbench · run {run['run_id']} · "
                   "every value links to an evidence record (Appendix A)")
    r.font.size = Pt(7.5)
    r.font.color.rgb = RGBColor.from_string(MUTED)

    # Title
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(0)
    r = p.add_run("Inspection Approval Note")
    r.bold, r.font.size = True, Pt(20)
    r.font.color.rgb = RGBColor.from_string(NAVY)
    _para(doc, f"{h['equipment_tag']} · {h['equipment_name']} · {h['unit']}", size=11,
          colour=MUTED, after=8)

    note_no = f"AN/{h['report_no'].split('/')[-1]}/D0"
    _kv(doc, [
        ("Note no.", note_no), ("Revision", "D0 — draft, not issued"),
        ("Source report", h["report_no"]), ("Generated", run["generated_at"]),
        ("Plant", h["plant"]), ("Inspection", f"{h['inspection_type']}, {h['inspection_date']}"),
    ])

    # Decision box
    fill, ink = OUTCOME_COLOURS[decision.outcome]
    box = _table(doc, [178])
    cell = box.add_row().cells[0]
    _shade(cell, fill)
    _write(cell, f"RULES OUTCOME: {decision.outcome}", bold=True, colour=ink, size=13)
    for t in decision.triggers + decision.review_items:
        p = cell.add_paragraph()
        p.paragraph_format.space_after = Pt(1)
        a = p.add_run(f"{t.rule_id} · {t.title}: ")
        a.bold, a.font.size = True, Pt(9)
        a.font.color.rgb = RGBColor.from_string(ink)
        b = p.add_run(f"{t.detail}  [{t.evidence_id}]")
        b.font.size = Pt(9)
    if decision.outcome == "NO TRIGGER":
        p = cell.add_paragraph()
        a = p.add_run("No evaluated rule triggered. This is not a statement of fitness for service.")
        a.italic, a.font.size = True, Pt(9)
    p = cell.add_paragraph()
    a = p.add_run(f"Rules evaluated: {', '.join(decision.evaluated)} · {decision.ruleset_version}")
    a.font.size = Pt(7.5)
    a.font.color.rgb = RGBColor.from_string(MUTED)
    _fix_widths(box)

    # 1. Summary
    _heading(doc, "1. Summary")
    _para(doc, summary.text, size=10)
    tries = len(summary.attempts)
    if summary.written_by.startswith("code"):
        how = f"Written by {summary.written_by}."
    else:
        how = (f"Drafted by {summary.written_by}; checked by code before use: every number appears in "
               f"the evidence, no approval language (attempt {tries} of 2).")
    _para(doc, how, size=7.5, colour=MUTED, italic=True)

    # 2. Equipment
    _heading(doc, "2. Equipment and inspection")
    _kv(doc, [
        ("Equipment", f"{h['equipment_tag']} — {h['equipment_name']}"), ("Service", h["service_fluid"]),
        ("Design pressure", f"{h['design_pressure_barg']} barg"), ("Design temp.", f"{h['design_temp_c']} °C"),
        ("Year built", str(h["year_built"])), ("Next due (report)", h["next_due_date"]),
        ("Inspector (report)", f"{h['inspector_name']}, {h['inspector_cert']}"),
        ("Corrosion rate (report)", f"{h['corrosion_rate_mm_yr']} mm/yr"),
    ])

    # 3. Findings
    _heading(doc, f"3. Findings ({len(ev.findings)})")
    t = _table(doc, [11, 28, 60, 20, 26, 33], ["ID", "Location", "Observation", "Severity", "Clause", "Recommendation"])
    for f in ev.findings:
        cells = _row(t, [f.finding_id, f.location, f.description, f.severity, f.ref_clause, f.recommendation])
        _shade(cells[3], SEVERITY_FILL.get(f.severity, "FFFFFF"))
        cells[3].paragraphs[0].runs[0].bold = True
    _fix_widths(t)

    # 4. Thickness
    _heading(doc, "4. Ultrasonic thickness survey (mm)")
    t = _table(doc, [16, 40, 18, 18, 18, 18, 20, 30],
               ["CML", "Location", "Nominal", "Previous", "Current", "Min. req.", "Margin", "Status"])
    breached = {tr.subject for tr in decision.triggers if tr.rule_id == "THK-01"}
    for r in ev.readings:
        current = r.current_mm
        if corrupt and r.cml_id in breached:
            current = current + Decimal("1.00")       # injected fault: the QA check must catch this
        margin = decision.margins_mm.get(r.cml_id)
        status = "BELOW MIN" if r.cml_id in breached else ("OK" if margin is not None else "CHECK")
        cells = _row(t, [r.cml_id, r.location, _mm(r.nominal_mm), _mm(r.previous_mm), _mm(current),
                         _mm(r.min_required_mm), "—" if margin is None else f"{margin:+.2f}", status],
                     align=None)
        for c in cells[2:7]:
            c.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
        s = cells[7].paragraphs[0].runs[0]
        s.bold = True
        s.font.color.rgb = RGBColor.from_string(BREACH_TEXT if r.cml_id in breached else OK_TEXT)
        if r.cml_id in breached:
            for c in cells:
                _shade(c, BREACH_FILL)
    _fix_widths(t)
    _para(doc, "Margin = current − minimum required, computed by the rules engine in exact decimals. "
               "Minimum values are taken from the report, never from a model's general knowledge.",
          size=7.5, colour=MUTED, italic=True)

    # 5. Actions
    _heading(doc, "5. Actions for engineering review")
    n = 0
    for tr in decision.triggers + decision.review_items:
        n += 1
        _para(doc, f"{n}. {tr.subject}: {tr.action} (rule {tr.rule_id})", size=9.5)
    for f in ev.findings:
        n += 1
        _para(doc, f"{n}. {f.finding_id}: {f.recommendation} (from the report)", size=9.5)

    # Sign-off
    _heading(doc, "6. Sign-off")
    t = _table(doc, [34, 60, 50, 34], ["Role", "Name", "Signature", "Date"])
    for role in ("Prepared", "Reviewed", "Approved"):
        _row(t, [role, "", "", ""])
    _fix_widths(t)
    _para(doc, "The workbench does not sign. A person completes this section after reviewing the "
               "evidence.", size=7.5, colour=MUTED, italic=True)

    # Appendix A -- evidence
    _heading(doc, "Appendix A — Evidence behind every critical value")
    t = _table(doc, [44, 38, 44, 52], ["Value", "Evidence ID", "Source (table / row)", "Source file · SHA-256"])
    for r in ev.readings:
        _row(t, [f"{r.cml_id}: {_mm(r.current_mm)} mm, min {_mm(r.min_required_mm)} mm", r.evidence_id,
                 f"{r.source.table} / {r.source.row}",
                 f"{Path(r.source.file).name} · {r.source.sha256[:12]}…"], size=7.5)
    for f in ev.findings:
        _row(t, [f"{f.finding_id}: {f.severity}", f.evidence_id, f"{f.source.table} / {f.source.row}",
                 f"{Path(f.source.file).name} · {f.source.sha256[:12]}…"], size=7.5)
    _fix_widths(t)

    # Appendix B -- verification record
    _heading(doc, "Appendix B — Verification record")
    rows = [
        ("Run ID", run["run_id"]), ("Evidence set SHA-256", ev.sha256()[:16] + "…"),
        ("Extraction", ev.extraction), ("Rule set", decision.ruleset_version),
        ("Summary", summary.written_by), ("Procedural graph", run["graph"]),
    ]
    if ev.problems:
        rows.insert(3, ("Reading problems", "; ".join(ev.problems)))
    if ev.reviewed:
        rows.append(("Entered by a person", "; ".join(
            f"{e['field']} = {e['entered']}, entered by {e['reviewer']} from the original report "
            f"(the scan read {e['read_as'] or 'nothing'})" for e in ev.reviewed)))
    kv = _kv(doc, rows)
    # Amber until a second reader cross-checks the values: the stand-in, and a single model's reading.
    if ev.extraction == STAND_IN or "single reader" in ev.extraction:
        _shade(kv.rows[2].cells[1], "FDEBC8")
    if ev.problems:
        _shade(kv.rows[3].cells[1], "FDEBC8")
    _para(doc, "Path taken through the procedural graph", size=8.5, bold=True, colour=NAVY, after=2)
    t = _table(doc, [38, 44, 16, 18, 62], ["Stage", "Agent", "Attempt", "Result", "Note"])
    for s in run["trace"]:
        cells = _row(t, [s.node, s.agent, str(s.attempt), s.status, s.note], size=7.5)
        if s.status != "ok":
            _shade(cells[3], "FDEBC8")
    _fix_widths(t)
    _para(doc, "Read-back check of this file", size=8.5, bold=True, colour=NAVY, after=2)
    t = _table(doc, [120, 20, 38], ["Check", "Result", "Detail"])
    if qa_results is None:
        _row(t, ["Performed by the QA stage after writing", "pending", ""], size=7.5)
    else:
        for name, ok, detail in qa_results:
            cells = _row(t, [name, "pass" if ok else "FAIL", detail], size=7.5)
            _shade(cells[1], "DCEFE3" if ok else "FADBD8")
    _fix_widths(t)

    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out)
    return out


# --- read-back verification ----------------------------------------------------------------

def _table_starting(doc, first: str):
    for t in doc.tables:
        if t.rows and t.rows[0].cells[0].text.strip() == first:
            return t
    return None


def verify(path: Path, ev: EvidenceSet, decision: Decision) -> list[tuple[str, bool, str]]:
    doc = Document(path)
    results: list[tuple[str, bool, str]] = []
    header = " ".join(p.text for p in doc.sections[0].header.paragraphs)
    body = "\n".join(p.text for p in doc.paragraphs)
    cells = "\n".join(c.text for t in doc.tables for row in t.rows for c in row.cells)
    everything = header + "\n" + body + "\n" + cells

    results.append(("Draft banner on every page", BANNER in header, ""))
    results.append((f"Rules outcome stated as {decision.outcome}",
                    f"RULES OUTCOME: {decision.outcome}" in cells, ""))

    ut = _table_starting(doc, "CML")
    breached = {tr.subject for tr in decision.triggers if tr.rule_id == "THK-01"}
    rows = {row.cells[0].text.strip(): row for row in ut.rows[1:]} if ut else {}
    for r in ev.readings:
        row = rows.get(r.cml_id)
        if row is None:
            results.append((f"{r.cml_id} row present", False, "missing"))
            continue
        got_cur, got_min = row.cells[4].text.strip(), row.cells[5].text.strip()
        ok = got_cur == _mm(r.current_mm) and got_min == _mm(r.min_required_mm)
        results.append((f"{r.cml_id} current and minimum match the evidence", ok,
                        f"{got_cur} / {got_min}" if not ok else ""))
        want = "BELOW MIN" if r.cml_id in breached else "OK"
        results.append((f"{r.cml_id} status is {want}", row.cells[7].text.strip() == want, ""))

    ft = _table_starting(doc, "ID")
    got = {row.cells[0].text.strip(): row.cells[3].text.strip() for row in ft.rows[1:]} if ft else {}
    ok = all(got.get(f.finding_id) == f.severity for f in ev.findings) and len(got) == len(ev.findings)
    results.append(("Every finding present with its severity", ok, "" if ok else str(got)))

    missing = sorted(i for i in ev.all_ids() if i not in cells)
    results.append(("Every evidence ID listed in Appendix A", not missing, ", ".join(missing[:3])))
    results.append(("No template placeholders", PLACEHOLDER.search(everything) is None, ""))

    so = _table_starting(doc, "Role")
    blank = so is not None and all(c.text.strip() == "" for row in so.rows[1:] for c in row.cells[1:])
    results.append(("Sign-off left blank for people", blank, ""))
    return results
