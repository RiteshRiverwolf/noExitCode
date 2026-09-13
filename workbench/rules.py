"""Rules Engine: plain code, no model. "The model explains, the code decides."

Outcomes follow ARCHITECTURE section 7.2:
  ESCALATE      an approved rule triggered
  NO TRIGGER    no evaluated rule triggered -- NOT a statement of fitness for service
  NEEDS REVIEW  evidence missing, ambiguous or conflicting

The rule set below is a demonstration set. The real one needs the asset, the
applicable standard edition, the operating context and an authorised
engineering interpretation; the note prints the rule-set version so a
reviewer can see which was applied.

Arithmetic is Decimal throughout: 12.32 < 12.7 must never depend on
floating-point rounding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from workbench.evidence import EvidenceSet

RULESET_VERSION = "demo-ruleset 2026-09-11 (not an approved MRPL rule set)"

RULES = {
    "THK-01": {
        "title": "Wall thickness below the minimum required",
        "action": "Engineering assessment of this CML before continued operation; "
                  "confirm the reading by repeat UT.",
    },
    "SEV-01": {
        "title": "Finding graded Major or Critical",
        "action": "Engineering review of the finding and its recommendation.",
    },
    "EVD-01": {
        "title": "Critical value missing or unreadable",
        "action": "Re-read the source, or have a person confirm the value.",
    },
}
ESCALATING_SEVERITIES = {"Major", "Critical"}
GRADES = {"Critical", "Major", "Minor", "Observation"}


@dataclass
class Trigger:
    rule_id: str
    evidence_id: str
    subject: str
    detail: str

    @property
    def title(self) -> str:
        return RULES[self.rule_id]["title"]

    @property
    def action(self) -> str:
        return RULES[self.rule_id]["action"]


@dataclass
class Decision:
    outcome: str
    triggers: list[Trigger]
    review_items: list[Trigger]
    margins_mm: dict[str, Decimal] = field(default_factory=dict)  # CML -> current - minimum
    evaluated: list[str] = field(default_factory=lambda: sorted(RULES))
    ruleset_version: str = RULESET_VERSION


def evaluate(ev: EvidenceSet) -> Decision:
    triggers: list[Trigger] = []
    review: list[Trigger] = []
    margins: dict[str, Decimal] = {}

    for r in ev.readings:
        if r.current_mm is None or r.min_required_mm is None:
            missing = "current thickness" if r.current_mm is None else "minimum required"
            review.append(Trigger("EVD-01", r.evidence_id, r.cml_id, f"{r.cml_id}: {missing} missing"))
            continue
        margin = r.current_mm - r.min_required_mm
        margins[r.cml_id] = margin
        if r.current_mm < r.min_required_mm:
            triggers.append(Trigger(
                "THK-01", r.evidence_id, r.cml_id,
                f"{r.cml_id} ({r.location}): current {r.current_mm} mm is below the minimum "
                f"required {r.min_required_mm} mm, by {-margin} mm",
            ))

    for f in ev.findings:
        if f.severity not in GRADES:
            # An unread grade is not a Minor one. Skipped silently, a "Major" that
            # OCR left empty is a missed escalation -- and on a report with no
            # other trigger the outcome becomes NO TRIGGER. Found 2026-09-13 on
            # insp_1010's medium scan (bench/stage2/unreadable_severity_test.py).
            review.append(Trigger("EVD-01", f.evidence_id, f.finding_id,
                                  f"{f.finding_id}: severity unreadable ({f.severity!r})"))
            continue
        if f.severity in ESCALATING_SEVERITIES:
            triggers.append(Trigger(
                "SEV-01", f.evidence_id, f.finding_id,
                f"{f.finding_id} graded {f.severity}: {f.description}",
            ))

    outcome = "ESCALATE" if triggers else ("NEEDS REVIEW" if review else "NO TRIGGER")
    return Decision(outcome=outcome, triggers=triggers, review_items=review, margins_mm=margins)


def allowed_numbers(ev: EvidenceSet, decision: Decision) -> set[str]:
    """Every number the model may use in its summary: those in the evidence and the rules' results."""
    nums: set[str] = set()
    for r in ev.readings:
        # Exact forms only: "12.32" or "12.320", never a rounded "12.3".
        for v in (r.nominal_mm, r.previous_mm, r.current_mm, r.min_required_mm):
            if v is not None:
                nums |= {str(v), f"{v:.2f}", str(v.normalize())}
    for m in decision.margins_mm.values():
        nums |= {str(abs(m)), f"{abs(m):.2f}"}
    for key in ("corrosion_rate_mm_yr", "remaining_life_yr", "design_pressure_barg", "design_temp_c", "year_built"):
        v = ev.header.get(key)
        if v is not None:
            nums |= {str(v), str(dec_or(v))}
    for f in ev.findings:  # clause numbers, and numbers in the report's own words ("35 mm", "W-12")
        for text in (f.ref_clause, f.finding_id, f.location, f.description, f.recommendation):
            nums |= set(_numbers(text))
    for r in ev.readings:
        nums |= set(_numbers(r.cml_id)) | set(_numbers(r.location))
    for key in ("equipment_tag", "report_no", "unit", "plant", "equipment_name",
                "inspection_type", "service_fluid", "inspector_cert"):
        nums |= set(_numbers(str(ev.header.get(key) or "")))
    nums |= set(_numbers(ev.header.get("inspection_date") or ""))
    nums |= set(_numbers(ev.header.get("next_due_date") or ""))
    nums |= {str(len(ev.findings)), str(len(ev.readings)), str(len(decision.triggers))}
    return nums


def dec_or(v) -> Decimal:
    return Decimal(str(v)).normalize()


def _numbers(text: str) -> list[str]:
    import re
    return re.findall(r"\d+(?:\.\d+)?", text)
