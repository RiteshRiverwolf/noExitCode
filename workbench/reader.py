"""Document Reader: a vision model reads the scanned report into evidence records.

STATUS (2026-09-12): not wired into the pipeline. Tests showed a whole-page
model never reports a damaged digit as unreadable -- it writes a plausible
number, sometimes one copied from another cell (results/stage1/NOTES.md).
This module becomes the *second* reader; the primary path is to be: text
layer if the PDF has one, else OCR (PP-StructureV3) with values placed in
cells by code. It also assumes the pages fit one model call; long reports
need per-page reading joined by CML id.

The model transcribes; code validates (ARCHITECTURE section 7.1):
  - every number must parse exactly as printed ("12.32", "12.32 mm"); anything
    else becomes a missing value, and the rules return NEEDS REVIEW (EVD-01);
  - code never repairs a digit, maps an unknown severity, or fills a gap;
  - every record keeps the page it came from, the text the model read for it,
    and the model and settings that read it.
Problems found by validation are listed on the evidence set; build_evidence
fails on them, so the graph re-reads once and then hands over to a person.

Tested 2026-09-12 on the synthetic corpus: qwen3.5:9b, insp_1002 clean scan,
0/25 critical fields wrong, 1/61 overall ("Shell head" for "Shell course").
Ollama did not enforce the JSON schema for this model (it wrapped values as
{"value": ...} inside a markdown fence), so the exact keys are also spelled
out in the prompt and the reply is unwrapped -- keys are never renamed.
"""

from __future__ import annotations

import base64
import json
import re
import time
from decimal import Decimal
from pathlib import Path

import httpx

from workbench.evidence import (CORPUS, HEADER_FIELDS, ROOT, EvidenceSet, Finding, Reading,
                                Source, sha256_file)

OLLAMA_CHAT = "http://127.0.0.1:11434/api/chat"
DEFAULT_READER = "qwen3.5:9b"
OPTIONS = {"temperature": 0, "num_ctx": 16384}
SEVERITIES = {"Critical", "Major", "Minor", "Observation"}
NUMERIC_HEADER = {"design_pressure_barg", "design_temp_c", "year_built",
                  "corrosion_rate_mm_yr", "remaining_life_yr"}
# A printed number, optionally followed by its unit. "12.3?" or "l2.32" do not match.
EXACT_NUMBER = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*(?:mm(?:/yr)?|barg|°\s*C|years?)?\s*$")

TEMPLATE = (
    '{"report_no": "", "equipment_tag": "", "equipment_name": "", "unit": "", "plant": "", '
    '"inspection_type": "", "inspection_date": "", "next_due_date": "", "inspector_name": "", '
    '"inspector_cert": "", "design_pressure_barg": "", "design_temp_c": "", "service_fluid": "", '
    '"year_built": "", "corrosion_rate_mm_yr": "", "remaining_life_yr": "", '
    '"findings": [{"finding_id": "", "page": 1, "location": "", "description": "", "severity": "", '
    '"ref_clause": "", "recommendation": ""}], '
    '"readings": [{"cml_id": "", "page": 1, "location": "", "nominal_mm": "", "previous_mm": "", '
    '"current_mm": "", "min_required_mm": "", "status": ""}]}'
)
PROMPT = (
    "These are the page images of one scanned equipment inspection report, in order. "
    "Transcribe it into JSON. Copy every value exactly as printed: do not round, convert, "
    "correct or guess. Numbers: copy the digits as printed, without units (e.g. '15.6' for "
    "'15.6 barg'). Findings come from section 2, with the recommendation for the same Ref "
    "from section 4. Readings come from the ultrasonic thickness survey table, one per CML "
    "row. 'page' is the 1-based number of the page image the row is printed on. "
    "If a value is unreadable, use null. Reply with only a JSON object with exactly these "
    "keys (no other keys, no markdown):\n" + TEMPLATE
)


def parse_reply(text: str) -> dict:
    """The model's JSON, tolerating a markdown fence and {"value": x} wrappers."""
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    data = json.loads(t)

    def unwrap(v):
        if isinstance(v, dict):
            if set(v) == {"value"}:
                return unwrap(v["value"])
            return {k: unwrap(x) for k, x in v.items()}
        if isinstance(v, list):
            return [unwrap(x) for x in v]
        return v
    return unwrap(data)


def exact_decimal(raw) -> Decimal | None:
    """The number exactly as printed, or None. Never a repaired or rounded value."""
    if raw is None or isinstance(raw, bool):
        return None
    m = EXACT_NUMBER.match(str(raw))
    return Decimal(m.group(1)) if m else None


def scan_pages(doc_id: str, quality: str) -> list[Path]:
    # The index lists the pages; the scan folders also hold stale page-2 images
    # from an earlier corpus build (found 2026-09-12), so never glob the folder.
    index = {e["doc_id"]: e for e in json.loads((CORPUS / "index.json").read_text(encoding="utf-8"))}
    return [CORPUS / p for p in index[doc_id]["scans"][quality]]


def read_pages(pages: list[Path], model: str = DEFAULT_READER) -> dict:
    """One call to the vision model with every page; returns the parsed reply and its record."""
    t0 = time.time()
    r = httpx.post(OLLAMA_CHAT, timeout=900, json={
        "model": model, "stream": False, "think": False, "options": OPTIONS,
        "messages": [{"role": "user", "content": PROMPT,
                      "images": [base64.b64encode(p.read_bytes()).decode() for p in pages]}]})
    body = r.json()
    if "error" in body:
        raise RuntimeError(f"{model}: {body['error']}")
    raw = body["message"]["content"]
    return {"data": parse_reply(raw), "raw_reply": raw, "model": model, "options": OPTIONS,
            "seconds": round(time.time() - t0, 1), "prompt_tokens": body.get("prompt_eval_count"),
            "reply_tokens": body.get("eval_count")}


def build(doc_id: str, pages: list[Path], read: dict) -> EvidenceSet:
    """Evidence records from a reading, with every validation problem listed."""
    data, model = read["data"], read["model"]
    rel = [p.relative_to(ROOT).as_posix() for p in pages]
    hashes = {f: sha256_file(p) for f, p in zip(rel, pages)}
    method = f"read from the scan by {model} (Ollama, temperature 0, thinking off)"
    problems: list[str] = []

    def src(table: str, row: str, item: dict) -> Source:
        page = item.get("page")
        if not isinstance(page, int) or not 1 <= page <= len(pages):
            if len(pages) > 1:
                problems.append(f"{row}: page {page!r} is not a page of this report")
            page = 1 if len(pages) == 1 else None
        f = rel[(page or 1) - 1]
        return Source(file=f, sha256=hashes[f], table=table, row=row, page=page,
                      raw_text=json.dumps({k: v for k, v in item.items() if k != "page"}, ensure_ascii=False))

    findings, seen = [], set()
    for item in data.get("findings") or []:
        fid = str(item.get("finding_id") or "").strip()
        if not fid or fid in seen:
            problems.append(f"finding with a missing or repeated Ref ({fid!r})")
            continue
        seen.add(fid)
        sev = str(item.get("severity") or "").strip()
        if sev not in SEVERITIES:
            problems.append(f"{fid}: severity {sev!r} is not one of the report's grades")
        findings.append(Finding(
            evidence_id=f"{doc_id}:F:{fid}", finding_id=fid, location=str(item.get("location") or ""),
            description=str(item.get("description") or ""), severity=sev,
            ref_clause=str(item.get("ref_clause") or ""), recommendation=str(item.get("recommendation") or ""),
            source=src("Findings", fid, item), method=method))

    readings, seen = [], set()
    for item in data.get("readings") or []:
        cml = str(item.get("cml_id") or "").strip()
        if not cml or cml in seen:
            problems.append(f"thickness row with a missing or repeated CML ({cml!r})")
            continue
        seen.add(cml)
        values = {k: exact_decimal(item.get(k)) for k in ("nominal_mm", "previous_mm", "current_mm", "min_required_mm")}
        for k in ("current_mm", "min_required_mm"):
            if values[k] is None:
                problems.append(f"{cml}: {k} not readable as printed ({item.get(k)!r})")
        readings.append(Reading(
            evidence_id=f"{doc_id}:T:{cml}", cml_id=cml, location=str(item.get("location") or ""),
            **values, min_source="stated in the report's UT survey table (Min. Req. column)",
            source=src("UT thickness survey", cml, item), method=method,
            review_status="needs review" if None in (values["current_mm"], values["min_required_mm"]) else "unreviewed"))
    if not readings:
        problems.append("no thickness readings were read")
    if not findings:
        problems.append("no findings were read")

    header = {}
    for k in HEADER_FIELDS:
        v = data.get(k)
        if k in NUMERIC_HEADER:
            header[k] = exact_decimal(v)
            if v not in (None, "") and header[k] is None:
                problems.append(f"header {k}: {v!r} is not a number as printed")
        else:
            header[k] = None if v is None else str(v).strip()
    for k in ("report_no", "equipment_tag"):
        if not header.get(k):
            problems.append(f"header {k} missing")

    return EvidenceSet(doc_id=doc_id, header=header, findings=findings, readings=readings,
                       extraction=f"{method}; single reader (a second reader for cross-checking is not built yet)",
                       source_files=hashes, problems=problems)


def from_scan(doc_id: str, quality: str = "medium", model: str = DEFAULT_READER) -> tuple[EvidenceSet, dict]:
    pages = scan_pages(doc_id, quality)
    read = read_pages(pages, model)
    return build(doc_id, pages, read), read
