"""Render the synthetic reference library to PDF, with its ground truth.

    .venv\\Scripts\\python bench\\library\\make_library.py        # -> data/library/

Writes, for the knowledge base to ingest and be scored against:

    data/library/pdf/<doc_id>.pdf   born-digital, so the Reader reads its text layer
    data/library/truth.json         every document and section, word for word
    data/library/questions.json     the retrieval test set, answerable and not

The documents go through the same Reader as the inspection reports: the library
is built from PDFs, not from these strings, so what gets searched is what was
actually read off the page.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle  # noqa: E402

from bench.library.content import DOCUMENTS, FOOTER, QUESTIONS  # noqa: E402

OUT = ROOT / "data" / "library"
KIND_LABEL = {"procedure": "Standard Operating Procedure", "register": "Register", "memo": "Internal memo"}

base = getSampleStyleSheet()
DOC_ID = ParagraphStyle("docid", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=9,
                        textColor=colors.HexColor("#374151"))
TITLE = ParagraphStyle("title", parent=base["Title"], fontSize=15, leading=19, alignment=0, spaceAfter=2)
META = ParagraphStyle("meta", parent=base["Normal"], fontSize=8.5, textColor=colors.HexColor("#6b7280"))
H2 = ParagraphStyle("h2", parent=base["Heading2"], fontSize=11.5, leading=15, spaceBefore=9, spaceAfter=3)
BODY = ParagraphStyle("body", parent=base["Normal"], fontSize=10, leading=14, spaceAfter=5)
CELL = ParagraphStyle("cell", parent=base["Normal"], fontSize=9, leading=12)
CELL_B = ParagraphStyle("cellb", parent=CELL, fontName="Helvetica-Bold")


def render(doc: dict, path: Path) -> None:
    story: list = [Paragraph(escape(doc["doc_id"]), DOC_ID), Paragraph(escape(doc["title"]), TITLE),
                   Paragraph(f"{KIND_LABEL[doc['kind']]} &nbsp;|&nbsp; Issued {doc['issued']}", META),
                   Spacer(1, 4 * mm)]
    if doc.get("memo"):
        m = doc["memo"]
        story.append(Table([[Paragraph("To", CELL_B), Paragraph(escape(m["to"]), CELL)],
                            [Paragraph("From", CELL_B), Paragraph(escape(m["from"]), CELL)],
                            [Paragraph("Date", CELL_B), Paragraph(escape(m["date"]), CELL)]],
                           colWidths=[25 * mm, 150 * mm]))
        story.append(Spacer(1, 3 * mm))
    for s in doc["sections"]:
        story.append(Paragraph(f"{s['id']}. {escape(s['title'])}", H2))
        for para in s["text"].split("\n\n"):
            story.append(Paragraph(escape(para), BODY))
        if s.get("table"):
            rows = [[Paragraph("Clause", CELL_B), Paragraph("Applied in", CELL_B), Paragraph("Subject", CELL_B)]]
            rows += [[Paragraph(escape(a), CELL), Paragraph(escape(b), CELL), Paragraph(escape(c), CELL)]
                     for a, b, c in s["table"]]
            t = Table(rows, colWidths=[52 * mm, 55 * mm, 68 * mm], repeatRows=1)
            t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9ca3af")),
                                   ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e7eb")),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            story.append(t)

    def footer(canvas, d) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#b91c1c"))
        canvas.drawString(16 * mm, 9 * mm, FOOTER)
        canvas.setFillColor(colors.HexColor("#6b7280"))
        canvas.drawRightString(A4[0] - 16 * mm, 5 * mm, f"{doc['doc_id']}  page {d.page}")
        canvas.restoreState()

    path.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                      topMargin=16 * mm, bottomMargin=18 * mm,
                      title=f"{doc['doc_id']} {doc['title']}").build(story, onFirstPage=footer,
                                                                     onLaterPages=footer)


def main() -> int:
    for doc in DOCUMENTS:
        render(doc, OUT / "pdf" / f"{doc['doc_id']}.pdf")
    truth = [{"doc_id": d["doc_id"], "kind": d["kind"], "title": d["title"], "issued": d["issued"],
              "file": f"data/library/pdf/{d['doc_id']}.pdf",
              "sections": [{"id": s["id"], "title": s["title"],
                            "text": s["text"] + ("\n\n" + "\n".join(" | ".join(r) for r in s["table"])
                                                 if s.get("table") else "")}
                           for s in d["sections"]]} for d in DOCUMENTS]
    (OUT / "truth.json").write_text(json.dumps({"footer": FOOTER, "documents": truth}, indent=2,
                                               ensure_ascii=False), encoding="utf-8")
    (OUT / "questions.json").write_text(json.dumps(QUESTIONS, indent=2, ensure_ascii=False), encoding="utf-8")
    sections = sum(len(d["sections"]) for d in DOCUMENTS)
    answerable = sum(1 for q in QUESTIONS if q.get("answerable", True))
    print(f"{len(DOCUMENTS)} documents, {sections} sections -> {OUT / 'pdf'}")
    print(f"{answerable} answerable questions, {len(QUESTIONS) - answerable} the library cannot answer")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
