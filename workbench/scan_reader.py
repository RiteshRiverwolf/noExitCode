"""Reading a real inspection report into evidence records -- the primary reader.

    .venv\\Scripts\\python -m workbench.scan_reader insp_1002 --quality medium
    .venv\\Scripts\\python -m workbench.scan_reader insp_1002 --pdf

This replaces the ground-truth stand-in that `evidence.from_ground_truth`
fills in. The chain, from ARCHITECTURE section 7.1 and the stage-1 findings:

    pagesource  document of any length -> per page, text with boxes
                (the PDF's own characters where it has them, OCR where it does not)
    tablemap    code places every value in its cell, tilt-corrected
    here        template of the MRPL report: which sections, which tables,
                which labels -> evidence records, each carrying its page, its
                box, the text it was read from and how it was read

What this reader will not do:
  * repair a value. "12.3?" is not turned into a number; the row goes to review.
  * fill a gap from anywhere else -- not from the model, not from a previous
    report, not from the Status column.
  * treat two readers agreeing as proof. Agreement is recorded, not trusted:
    OCR and qwen both read a blurred "12.32" as "12.3" (NOTES.md section 3).

Every critical value keeps the box it was read from, so the note can show the
engineer the picture of the cell. Against a digit that was physically lost
from the page, that person is the only remaining check.
"""

from __future__ import annotations

import argparse
import json
import re
from decimal import Decimal
from pathlib import Path

from workbench.evidence import (CORPUS, HEADER_FIELDS, ROOT, EvidenceSet, Finding, Reading,
                                Source, sha256_file)
from workbench.pagesource import Page, TextItem, open_document, open_pages
from workbench.tablemap import (Cell, TableSpec, check_cells, crop, find_table, norm,
                                read_pairs, read_paragraph)

# A printed number with the unit it is printed with ("15.6 barg", "250 °C",
# "380℃" -- OCR writes the degree sign as one character). "l2.32" or "12.3?"
# do not match, and are never repaired.
NUMBER_WITH_UNIT = re.compile(
    r"^\s*(-?\d+(?:\.\d+)?)\s*(?:mm(?:\s*/\s*yr)?|barg|℃|°?\s*[CF]|years?)?\s*$")
SEVERITIES = {"Critical", "Major", "Minor", "Observation"}

# Headings are matched on the bare text (workbench.tablemap.norm), because OCR
# drops the space in "2. INSPECTION FINDINGS".
SECTIONS = [
    ("identification", re.compile(r"^1equipmentidentification")),
    ("findings", re.compile(r"^2inspectionfindings")),
    ("thickness", re.compile(r"^3ultrasonicthicknesssurvey")),
    ("recommendations", re.compile(r"^4recommendations")),
    ("summary", re.compile(r"^5inspectorssummary")),
]

IDENTIFICATION_LABELS = {
    "reportno": "report_no", "equipmenttag": "equipment_tag", "equipment": "equipment_name",
    "unit": "unit", "plant": "plant", "servicefluid": "service_fluid",
    "yearbuilt": "year_built", "inspectiontype": "inspection_type",
    "designpressure": "design_pressure_barg", "designtemperature": "design_temp_c",
    "inspectiondate": "inspection_date", "nextduedate": "next_due_date",
    "inspectedby": "inspector_name", "certificationno": "inspector_cert",
}
SURVEY_LABELS = {"corrosionrate": "corrosion_rate_mm_yr", "estremaininglife": "remaining_life_yr"}
NUMERIC_HEADER = {"design_pressure_barg", "design_temp_c", "year_built",
                  "corrosion_rate_mm_yr", "remaining_life_yr"}

FINDINGS_TABLE = TableSpec(
    name="Findings",
    headers={"ref": "finding_id", "location": "location", "observation": "description",
             "severity": "severity", "refclause": "ref_clause"},
    row_id=re.compile(r"F-\d+"),
    single_item=("finding_id", "severity"),
)
THICKNESS_TABLE = TableSpec(
    name="UT thickness survey",
    headers={"cml": "cml_id", "location": "location", "nominal": "nominal_mm",
             "previous": "previous_mm", "current": "current_mm", "minreq": "min_required_mm",
             "status": "status"},
    row_id=re.compile(r"CML-\d+"),
    numeric=("nominal_mm", "previous_mm", "current_mm", "min_required_mm"),
    single_item=("cml_id",),
)
RECOMMENDATION_TABLE = TableSpec(
    name="Recommendations",
    headers={"ref": "finding_id", "recommendedaction": "recommendation"},
    row_id=re.compile(r"F-\d+"),
    single_item=("finding_id",),
)


# --- sections ----------------------------------------------------------------

def section_regions(pages: list[Page]) -> dict[str, list[tuple[Page, float, float]]]:
    """Where each numbered section sits, page by page.

    A section that runs past the foot of a page simply continues at the top of
    the next one -- which is how a long thickness table behaves, and why the
    region is a list.
    """
    regions: dict[str, list[tuple[Page, float, float]]] = {name: [] for name, _ in SECTIONS}
    open_section: str | None = None
    for page in pages:
        # Each heading is kept as (its top, its bottom): a section's content
        # starts below its own heading and stops *above* the next one.
        marks: list[tuple[float, float, str]] = []
        for item in page.items:
            bare = norm(item.text)
            for name, pattern in SECTIONS:
                if pattern.match(bare):
                    marks.append((item.bbox[1], item.bbox[3], name))
                    break
        marks.sort()
        if open_section and (not marks or marks[0][0] > 0):
            regions[open_section].append((page, 0.0, marks[0][0] if marks else page.height))
        for n, (_, heading_bottom, name) in enumerate(marks):
            end = marks[n + 1][0] if n + 1 < len(marks) else page.height
            regions[name].append((page, heading_bottom, end))
            open_section = name
    return regions


# --- reading the pieces ------------------------------------------------------

def exact_decimal(text: str | None) -> Decimal | None:
    """The number exactly as printed, or None. Never rounded, never repaired."""
    if not text:
        return None
    m = NUMBER_WITH_UNIT.match(str(text))
    return Decimal(m.group(1)) if m else None


def read_table_rows(spec: TableSpec, regions: list[tuple[Page, float, float]],
                    problems: list[str], notes: list[str]) -> dict[str, dict[str, Cell]]:
    """One table, gathered across every page it runs over, joined by row id.

    A table continued on the next page repeats its header (the report is built
    that way), so each page is read on its own and the rows are merged. The
    same id appearing twice with different text is a problem, not a silent
    overwrite.
    """
    rows: dict[str, dict[str, Cell]] = {}
    found_on = []
    for page, top, bottom in regions:
        table = find_table(page, spec, top, bottom, notes)
        if table is None:
            continue
        check_cells(table, page)
        found_on.append(page.number)
        problems.extend(table.problems)
        for row_id, cells in table.rows.items():
            if row_id in rows:
                old, new = rows[row_id], cells
                if any(old[f].text != new[f].text for f in new):
                    problems.append(f"{spec.name}: {row_id} appears on more than one page "
                                    f"with different values")
                continue
            rows[row_id] = cells
    if not rows:
        problems.append(f"{spec.name}: the table was not found")
    return rows


def read_identification(regions, problems: list[str], notes: list[str]) -> tuple[dict, dict[str, Cell]]:
    cells: dict[str, Cell] = {}
    for page, top, bottom in regions:
        for name, cell in read_pairs(page, IDENTIFICATION_LABELS, top, bottom, notes).items():
            cells.setdefault(name, cell)
    header: dict = {}
    for field in HEADER_FIELDS:
        cell = cells.get(field)
        if cell is None or not cell.items:
            header[field] = None
            if field not in ("corrosion_rate_mm_yr", "remaining_life_yr"):
                problems.append(f"identification: {field} not found on the page")
            continue
        if field in NUMERIC_HEADER:
            header[field] = exact_decimal(cell.text)
            if header[field] is None:
                problems.append(f"identification: {field} is not a number as printed ({cell.text!r})")
        else:
            header[field] = cell.text
    return header, cells


def read_survey_extras(regions, header: dict, cells: dict[str, Cell], problems: list[str],
                       notes: list[str]) -> None:
    """Corrosion rate and remaining life: printed under the thickness table."""
    for page, top, bottom in regions:
        for name, cell in read_pairs(page, SURVEY_LABELS, top, bottom, notes).items():
            cells.setdefault(name, cell)
            value = exact_decimal(cell.text)
            if value is None:
                problems.append(f"survey: {name} is not a number as printed ({cell.text!r})")
            header[name] = value


# --- evidence ----------------------------------------------------------------

def _source(page: Page, table: str, row: str, cell: Cell | None, hashes: dict[str, str],
            crop_path: str | None = None) -> Source:
    bbox = cell.bbox if cell else None
    return Source(
        file=page.source_file, sha256=hashes[page.source_file], table=table, row=row,
        page=page.number, bbox=[round(v, 1) for v in bbox] if bbox else None,
        raw_text=cell.text if cell else None,
        score=round(cell.score, 4) if cell else None, read_by=page.read_by, crop=crop_path)


def build_evidence(doc_id: str, pages: list[Page], crop_dir: Path | None = None) -> EvidenceSet:
    """Evidence records from the pages, with every problem the checks found."""
    problems: list[str] = []
    notes: list[str] = []          # what was read as what -- not problems, but on the record
    regions = section_regions(pages)
    by_number = {p.number: p for p in pages}
    hashes = {p.source_file: sha256_file(Path(ROOT / p.source_file)) for p in pages}

    header, id_cells = read_identification(regions["identification"], problems, notes)
    read_survey_extras(regions["thickness"], header, id_cells, problems, notes)
    finding_rows = read_table_rows(FINDINGS_TABLE, regions["findings"], problems, notes)
    reading_rows = read_table_rows(THICKNESS_TABLE, regions["thickness"], problems, notes)
    rec_rows = read_table_rows(RECOMMENDATION_TABLE, regions["recommendations"], problems, notes)

    read_by = sorted({p.read_by for p in pages})
    method = f"read from the document by {' and '.join(read_by)}, values placed in cells by code"

    def cut(cell: Cell, name: str) -> str | None:
        if crop_dir is None or not cell.bbox:
            return None
        path = crop(by_number[cell.page], cell.bbox, Path(crop_dir) / f"{name}.png")
        return path.relative_to(ROOT).as_posix()

    findings: list[Finding] = []
    for finding_id, cells in sorted(finding_rows.items()):
        page = by_number[cells["severity"].page]
        severity = cells["severity"].text
        if severity not in SEVERITIES:
            problems.append(f"{finding_id}: severity {severity!r} is not one of the report's grades")
        for name, cell in cells.items():
            problems.extend(f"{finding_id}.{name}: {p}" for p in cell.problems)
        rec_cell = rec_rows.get(finding_id, {}).get("recommendation")
        if rec_cell is None or not rec_cell.items:
            problems.append(f"{finding_id}: no recommended action found in section 4")
        findings.append(Finding(
            evidence_id=f"{doc_id}:F:{finding_id}", finding_id=finding_id,
            location=cells["location"].text, description=cells["description"].text,
            severity=severity, ref_clause=cells["ref_clause"].text,
            recommendation=rec_cell.text if rec_cell else "",
            source=_source(page, FINDINGS_TABLE.name, finding_id, cells["severity"], hashes,
                           cut(cells["severity"], f"{finding_id}_severity")),
            method=method))

    readings: list[Reading] = []
    for cml_id, cells in sorted(reading_rows.items()):
        page = by_number[cells["cml_id"].page]
        values = {f: exact_decimal(cells[f].text) for f in THICKNESS_TABLE.numeric}
        bad = [f for f in THICKNESS_TABLE.numeric if cells[f].problems or values[f] is None]
        for name in THICKNESS_TABLE.numeric + ("cml_id", "location", "status"):
            problems.extend(f"{cml_id}.{name}: {p}" for p in cells[name].problems)
        # The report's own Status column is evidence, never the decision: the
        # rules recompute it from the numbers (workbench/rules.py).
        readings.append(Reading(
            evidence_id=f"{doc_id}:T:{cml_id}", cml_id=cml_id, location=cells["location"].text,
            **values, min_source="stated in the report's UT survey table (Min. Req. column)",
            source=_source(page, THICKNESS_TABLE.name, cml_id, cells["current_mm"], hashes,
                           cut(cells["current_mm"], f"{cml_id}_current")),
            method=method,
            review_status="needs review" if bad or values["current_mm"] is None
            or values["min_required_mm"] is None else "unreviewed",
            printed_status=cells["status"].text or None))

    extra = set(rec_rows) - set(finding_rows)
    if extra:
        problems.append(f"section 4 recommends action for {', '.join(sorted(extra))}, "
                        f"which is not in the findings table")
    if not readings:
        problems.append("no thickness readings were read")
    if not findings:
        problems.append("no findings were read")

    return EvidenceSet(
        doc_id=doc_id, header=header, findings=findings, readings=readings,
        extraction=f"{method}; single reader (cross-check with a second reader is separate)",
        source_files=hashes, problems=problems, notes=notes,
        pages=[{"page": p.number, "file": p.source_file, "read_by": p.read_by,
                "image": p.image_path.relative_to(ROOT).as_posix()
                if p.image_path.is_relative_to(ROOT) else str(p.image_path),
                "texts": len(p.items)} for p in pages])


# --- the corpus, for testing --------------------------------------------------

def corpus_pages(doc_id: str, quality: str | None, work_dir: Path) -> list[Page]:
    """One corpus report: its scans at a quality, or its born-digital PDF.

    The page list comes from index.json, never from a folder listing.
    """
    if quality is None:
        return open_document(CORPUS / "pdf" / f"{doc_id}.pdf", work_dir)
    index = {e["doc_id"]: e for e in json.loads((CORPUS / "index.json").read_text(encoding="utf-8"))}
    return open_pages([CORPUS / p for p in index[doc_id]["scans"][quality]], work_dir)


def from_corpus(doc_id: str, quality: str | None = "medium",
                work_dir: Path | None = None, crop_dir: Path | None = None) -> EvidenceSet:
    work_dir = work_dir or ROOT / "runs" / "_reader"
    return build_evidence(doc_id, corpus_pages(doc_id, quality, work_dir), crop_dir)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("doc_id")
    ap.add_argument("--quality", default="medium", choices=["clean", "light", "medium", "heavy"])
    ap.add_argument("--pdf", action="store_true", help="read the born-digital PDF, not a scan")
    ap.add_argument("--crops", action="store_true", help="also cut the crop for every critical value")
    args = ap.parse_args()

    work = ROOT / "runs" / "_reader" / args.doc_id
    ev = from_corpus(args.doc_id, None if args.pdf else args.quality, work,
                     work / "crops" if args.crops else None)
    print(ev.to_json())
    print(f"\n{len(ev.findings)} findings, {len(ev.readings)} readings, "
          f"{len(ev.problems)} problem(s)")
    for p in ev.problems:
        print(f"  - {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
