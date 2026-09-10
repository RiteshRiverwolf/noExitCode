"""Render an InspectionReport to a PDF that looks like a real refinery document.

Deliberately laid out with the things that make OCR and extraction non-trivial:
a header block, dense key/value tables, a numeric table with units, and free
text. If our pipeline handles this it handles a real scanned report.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .schema import InspectionReport

SEVERITY_COLOURS = {
    "Observation": colors.HexColor("#6b7280"),
    "Minor": colors.HexColor("#b45309"),
    "Major": colors.HexColor("#c2410c"),
    "Critical": colors.HexColor("#b91c1c"),
}

_styles = getSampleStyleSheet()

BODY = ParagraphStyle(
    "body", parent=_styles["Normal"], fontName="Helvetica", fontSize=8,
    leading=10.5,
)
CELL = ParagraphStyle("cell", parent=BODY, fontSize=7.5, leading=9.5)
CELL_B = ParagraphStyle("cellb", parent=CELL, fontName="Helvetica-Bold")
TITLE = ParagraphStyle(
    "title", parent=_styles["Normal"], fontName="Helvetica-Bold", fontSize=13,
    leading=16, alignment=TA_CENTER,
)
SUBTITLE = ParagraphStyle(
    "subtitle", parent=_styles["Normal"], fontName="Helvetica", fontSize=8.5,
    leading=11, alignment=TA_CENTER, textColor=colors.HexColor("#374151"),
)
H2 = ParagraphStyle(
    "h2", parent=_styles["Normal"], fontName="Helvetica-Bold", fontSize=9,
    leading=12, spaceBefore=8, spaceAfter=4,
)

GRID = colors.HexColor("#9ca3af")
HEADER_BG = colors.HexColor("#e5e7eb")


def _kv_table(rows: list[tuple[str, str]], col_widths) -> Table:
    """Two-column key/value pairs laid out as a 4-column table."""
    data = []
    for i in range(0, len(rows), 2):
        chunk = rows[i : i + 2]
        line = []
        for k, v in chunk:
            line.extend([Paragraph(k, CELL_B), Paragraph(str(v), CELL)])
        while len(line) < 4:
            line.append(Paragraph("", CELL))
        data.append(line)

    t = Table(data, colWidths=col_widths)
    t.setStyle(
        TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, GRID),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BACKGROUND", (0, 0), (0, -1), HEADER_BG),
            ("BACKGROUND", (2, 0), (2, -1), HEADER_BG),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ])
    )
    return t


def render_report(report: InspectionReport, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"Inspection Report {report.report_no}",
    )

    story: list = []
    avail = doc.width

    # --- Header -----------------------------------------------------------
    story.append(Paragraph("MANGALORE REFINERY AND PETROCHEMICALS LIMITED", TITLE))
    story.append(Paragraph(
        "Inspection Department &nbsp;|&nbsp; Static Equipment Inspection Record", SUBTITLE))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("EQUIPMENT INSPECTION REPORT", ParagraphStyle(
        "hdr", parent=TITLE, fontSize=10.5,
        textColor=colors.HexColor("#111827"))))
    story.append(Spacer(1, 3 * mm))

    # --- Identification ---------------------------------------------------
    story.append(Paragraph("1. EQUIPMENT IDENTIFICATION", H2))
    story.append(_kv_table(
        [
            ("Report No.", report.report_no),
            ("Equipment Tag", report.equipment_tag),
            ("Equipment", report.equipment_name),
            ("Unit", report.unit),
            ("Plant", report.plant),
            ("Service Fluid", report.service_fluid),
            ("Year Built", report.year_built),
            ("Inspection Type", report.inspection_type),
            ("Design Pressure", f"{report.design_pressure_barg} barg"),
            ("Design Temperature", f"{report.design_temp_c} °C"),
            ("Inspection Date", report.inspection_date),
            ("Next Due Date", report.next_due_date),
            ("Inspected By", report.inspector_name),
            ("Certification No.", report.inspector_cert),
        ],
        col_widths=[avail * 0.19, avail * 0.31, avail * 0.19, avail * 0.31],
    ))

    # --- Findings ---------------------------------------------------------
    story.append(Paragraph("2. INSPECTION FINDINGS", H2))
    head = [
        Paragraph("Ref", CELL_B), Paragraph("Location", CELL_B),
        Paragraph("Observation", CELL_B), Paragraph("Severity", CELL_B),
        Paragraph("Ref. Clause", CELL_B),
    ]
    rows = [head]
    for f in report.findings:
        rows.append([
            Paragraph(f.finding_id, CELL),
            Paragraph(f.location, CELL),
            Paragraph(f.description, CELL),
            Paragraph(f"<b>{f.severity}</b>", ParagraphStyle(
                "sev", parent=CELL, textColor=SEVERITY_COLOURS[f.severity])),
            Paragraph(f.ref_clause, CELL),
        ])

    t = Table(rows, colWidths=[avail * 0.06, avail * 0.17, avail * 0.45,
                               avail * 0.12, avail * 0.20], repeatRows=1)
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, GRID),
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t)

    # --- Thickness survey -------------------------------------------------
    story.append(Paragraph("3. ULTRASONIC THICKNESS SURVEY (mm)", H2))
    head = [Paragraph(h, CELL_B) for h in
            ("CML", "Location", "Nominal", "Previous", "Current", "Min. Req.", "Status")]
    rows = [head]
    for r in report.readings:
        breached = r.is_below_minimum
        rows.append([
            Paragraph(r.cml_id, CELL),
            Paragraph(r.location, CELL),
            Paragraph(f"{r.nominal_mm:.1f}", CELL),
            Paragraph(f"{r.previous_mm:.2f}", CELL),
            Paragraph(f"{r.current_mm:.2f}", CELL),
            Paragraph(f"{r.min_required_mm:.1f}", CELL),
            Paragraph(
                "<b>BELOW MIN</b>" if breached else "Acceptable",
                ParagraphStyle("st", parent=CELL, textColor=(
                    colors.HexColor("#b91c1c") if breached
                    else colors.HexColor("#15803d"))),
            ),
        ])

    t = Table(rows, colWidths=[avail * 0.09, avail * 0.29, avail * 0.10,
                               avail * 0.11, avail * 0.11, avail * 0.11,
                               avail * 0.19], repeatRows=1)
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, GRID),
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (2, 1), (5, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]))
    story.append(t)

    story.append(Spacer(1, 2 * mm))
    story.append(_kv_table(
        [
            ("Corrosion Rate", f"{report.corrosion_rate_mm_yr} mm/yr"),
            ("Est. Remaining Life", f"{report.remaining_life_yr} years"),
        ],
        col_widths=[avail * 0.19, avail * 0.31, avail * 0.19, avail * 0.31],
    ))

    # --- Recommendations --------------------------------------------------
    story.append(Paragraph("4. RECOMMENDATIONS", H2))
    rows = [[Paragraph("Ref", CELL_B), Paragraph("Recommended Action", CELL_B)]]
    for f in report.findings:
        rows.append([Paragraph(f.finding_id, CELL),
                     Paragraph(f.recommendation, CELL)])
    t = Table(rows, colWidths=[avail * 0.06, avail * 0.94], repeatRows=1)
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, GRID),
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t)

    # --- Summary + signature ---------------------------------------------
    story.append(Paragraph("5. INSPECTOR'S SUMMARY", H2))
    story.append(Paragraph(report.summary, BODY))
    story.append(Spacer(1, 8 * mm))

    sig = Table(
        [[Paragraph("Inspected By", CELL_B), Paragraph("Reviewed By", CELL_B),
          Paragraph("Approved By", CELL_B)],
         [Paragraph(f"{report.inspector_name}<br/>{report.inspector_cert}", CELL),
          Paragraph("Sr. Inspection Engineer", CELL),
          Paragraph("Head — Inspection Dept.", CELL)],
         [Paragraph("<br/><br/>", CELL)] * 3],
        colWidths=[avail / 3] * 3,
    )
    sig.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, GRID),
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(KeepTogether(sig))

    doc.build(story)
    return out_path
