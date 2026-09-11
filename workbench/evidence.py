"""Evidence records: one per critical value, carrying where it came from.

The stage 1 contract from ARCHITECTURE section 7.1. Extraction from the scan
is not built yet, so `from_ground_truth` builds the records from the test
corpus's ground-truth file and labels them that way. Every note made from
them says so in its verification record. When the Document Reader and
Evidence Builder exist, they produce the same records from the scan itself,
with page, cell position and raw OCR text filled in.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "data" / "corpus"
STAND_IN = "ground-truth stand-in (extraction from the scan is not built yet)"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dec(value) -> Decimal | None:
    """Exact decimal from a reported number; None when the value is missing."""
    return None if value is None else Decimal(str(value))


@dataclass
class Source:
    file: str                      # path relative to the repo root
    sha256: str
    table: str
    row: str
    page: int | None = None        # set by extraction; unknown for the stand-in
    bbox: list[float] | None = None
    raw_text: str | None = None


@dataclass
class Reading:
    evidence_id: str
    cml_id: str
    location: str
    nominal_mm: Decimal | None
    previous_mm: Decimal | None
    current_mm: Decimal | None
    min_required_mm: Decimal | None
    min_source: str                # where the minimum comes from -- never model knowledge
    source: Source
    method: str
    review_status: str = "unreviewed"


@dataclass
class Finding:
    evidence_id: str
    finding_id: str
    location: str
    description: str
    severity: str
    ref_clause: str
    recommendation: str
    source: Source
    method: str


@dataclass
class EvidenceSet:
    doc_id: str
    header: dict
    findings: list[Finding]
    readings: list[Reading]
    extraction: str
    source_files: dict[str, str] = field(default_factory=dict)  # file -> sha256

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False,
                          default=lambda v: str(v) if isinstance(v, Decimal) else v)

    def sha256(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    def all_ids(self) -> set[str]:
        return {f.evidence_id for f in self.findings} | {r.evidence_id for r in self.readings}


HEADER_FIELDS = [
    "report_no", "equipment_tag", "equipment_name", "unit", "plant", "inspection_type",
    "inspection_date", "next_due_date", "inspector_name", "inspector_cert",
    "design_pressure_barg", "design_temp_c", "service_fluid", "year_built",
    "corrosion_rate_mm_yr", "remaining_life_yr",
]


def from_ground_truth(doc_id: str, scan_quality: str = "medium") -> EvidenceSet:
    """Evidence records for one corpus report, built from its ground-truth file."""
    truth_path = CORPUS / "truth" / f"{doc_id}.json"
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    index = {e["doc_id"]: e for e in json.loads((CORPUS / "index.json").read_text(encoding="utf-8"))}
    scans = [CORPUS / p for p in index[doc_id]["scans"][scan_quality]]
    first_scan = scans[0].relative_to(ROOT).as_posix()
    source_files = {p.relative_to(ROOT).as_posix(): sha256_file(p) for p in scans}

    def src(table: str, row: str) -> Source:
        return Source(file=first_scan, sha256=source_files[first_scan], table=table, row=row)

    findings = [
        Finding(
            evidence_id=f"{doc_id}:F:{f['finding_id']}",
            finding_id=f["finding_id"], location=f["location"], description=f["description"],
            severity=f["severity"], ref_clause=f["ref_clause"], recommendation=f["recommendation"],
            source=src("Findings", f["finding_id"]), method=STAND_IN,
        )
        for f in truth["findings"]
    ]
    readings = [
        Reading(
            evidence_id=f"{doc_id}:T:{r['cml_id']}",
            cml_id=r["cml_id"], location=r["location"],
            nominal_mm=dec(r.get("nominal_mm")), previous_mm=dec(r.get("previous_mm")),
            current_mm=dec(r.get("current_mm")), min_required_mm=dec(r.get("min_required_mm")),
            min_source="stated in the report's UT survey table (Min. Req. column)",
            source=src("UT thickness survey", r["cml_id"]), method=STAND_IN,
        )
        for r in truth["readings"]
    ]
    header = {k: truth.get(k) for k in HEADER_FIELDS}
    return EvidenceSet(doc_id=doc_id, header=header, findings=findings, readings=readings,
                       extraction=STAND_IN, source_files=source_files)
