"""Data model for synthetic refinery inspection reports.

Every generated document carries a matching ground-truth record. That is the
whole point of generating rather than scraping: we know exactly what is on the
page, so OCR character error rate and field-extraction accuracy are measurable
instead of eyeballed.

Content and vocabulary are modelled on OISD standards and API 510/570 structure.
Nothing here is copied from those documents -- see docs/DATASETS.md section 2.3.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


SEVERITIES = ("Observation", "Minor", "Major", "Critical")


@dataclass
class ThicknessReading:
    """One UT thickness measurement point (CML = Condition Monitoring Location)."""

    cml_id: str
    location: str
    nominal_mm: float
    previous_mm: float
    current_mm: float
    min_required_mm: float

    @property
    def loss_mm(self) -> float:
        return round(self.previous_mm - self.current_mm, 2)

    @property
    def is_below_minimum(self) -> bool:
        return self.current_mm < self.min_required_mm

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["loss_mm"] = self.loss_mm
        d["is_below_minimum"] = self.is_below_minimum
        return d


@dataclass
class Finding:
    """A single inspection finding. `ref_clause` is what the agent must cite."""

    finding_id: str
    location: str
    description: str
    severity: str
    ref_clause: str
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InspectionReport:
    report_no: str
    equipment_tag: str
    equipment_name: str
    unit: str
    plant: str
    inspection_type: str
    inspection_date: str
    next_due_date: str
    inspector_name: str
    inspector_cert: str
    design_pressure_barg: float
    design_temp_c: int
    service_fluid: str
    year_built: int
    corrosion_rate_mm_yr: float
    remaining_life_yr: float
    findings: list[Finding] = field(default_factory=list)
    readings: list[ThicknessReading] = field(default_factory=list)
    summary: str = ""
    # Whether the inspector's summary states the escalation conclusion outright.
    # Real reports vary. When False the agent must derive the verdict from the
    # findings and thickness tables instead of reading it off a sentence --
    # which is the capability we actually care about measuring.
    summary_leaks_conclusion: bool = True

    # --- derived properties the agent should be able to reason to ---

    @property
    def highest_severity(self) -> str:
        """Worst severity present, by SEVERITIES ordering."""
        if not self.findings:
            return "Observation"
        return max(self.findings, key=lambda f: SEVERITIES.index(f.severity)).severity

    @property
    def breached_cmls(self) -> list[str]:
        return [r.cml_id for r in self.readings if r.is_below_minimum]

    @property
    def requires_approval(self) -> bool:
        """The decision the R3 agent must reach on its own.

        Escalation is triggered by EITHER a Major/Critical finding OR any CML
        measured below minimum required thickness. Deliberately two independent
        triggers in two different tables: an agent that reads only the findings
        table will miss the thickness-only cases, which is exactly the failure
        mode worth catching before a demo.
        """
        return self.highest_severity in ("Major", "Critical") or bool(self.breached_cmls)

    @property
    def approval_reason(self) -> str:
        """Why escalation was (or wasn't) required -- lets us score not just the
        verdict but whether the agent got it right for the right reason."""
        sev = self.highest_severity in ("Major", "Critical")
        breach = bool(self.breached_cmls)
        if sev and breach:
            return "severity_and_thickness"
        if sev:
            return "severity"
        if breach:
            return "thickness_only"
        return "none"

    def to_ground_truth(self) -> dict[str, Any]:
        """Full ground truth for scoring extraction accuracy."""
        return {
            "report_no": self.report_no,
            "equipment_tag": self.equipment_tag,
            "equipment_name": self.equipment_name,
            "unit": self.unit,
            "plant": self.plant,
            "inspection_type": self.inspection_type,
            "inspection_date": self.inspection_date,
            "next_due_date": self.next_due_date,
            "inspector_name": self.inspector_name,
            "inspector_cert": self.inspector_cert,
            "design_pressure_barg": self.design_pressure_barg,
            "design_temp_c": self.design_temp_c,
            "service_fluid": self.service_fluid,
            "year_built": self.year_built,
            "corrosion_rate_mm_yr": self.corrosion_rate_mm_yr,
            "remaining_life_yr": self.remaining_life_yr,
            "summary": self.summary,
            "summary_leaks_conclusion": self.summary_leaks_conclusion,
            "findings": [f.to_dict() for f in self.findings],
            "readings": [r.to_dict() for r in self.readings],
            # Derived expectations -- what a correct agent run should conclude
            "expected": {
                "highest_severity": self.highest_severity,
                "requires_approval": self.requires_approval,
                "approval_reason": self.approval_reason,
                "breached_cmls": self.breached_cmls,
                "finding_count": len(self.findings),
                "cited_clauses": sorted({f.ref_clause for f in self.findings}),
            },
        }
