"""Synthetic inspection-report corpus with ground truth.

Scope note: real documents (CSB, MRPL tenders) cover OCR benchmarking and KB
grounding -- see docs/DATASETS.md. This package exists for the one job they
cannot do: providing *field-level* ground truth so the R3 extraction step and
the escalation decision can be scored.
"""

from .schema import Finding, InspectionReport, ThicknessReading
from .content import generate_report
from .render import render_report
from .degrade import PROFILES, degrade, degrade_pdf, pdf_to_images

__all__ = [
    "Finding",
    "InspectionReport",
    "ThicknessReading",
    "generate_report",
    "render_report",
    "PROFILES",
    "degrade",
    "degrade_pdf",
    "pdf_to_images",
]
