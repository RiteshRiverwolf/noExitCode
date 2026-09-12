"""Score the reader against the corpus ground truth.

    .venv\\Scripts\\python bench\\stage2\\reader_score.py --pdf
    .venv\\Scripts\\python bench\\stage2\\reader_score.py --quality medium insp_1002

Every field the reader produced is compared with what was printed. Three
outcomes, and only the third is a real failure:

    right            the value matches the ground truth
    caught           wrong or missing, AND the reader said so (a problem, or
                     the row marked "needs review") -- the pipeline stops
    ACCEPTED WRONG   wrong, and nothing flagged it. This is the number that
                     matters: it is what would reach an approval note.

Critical fields are the ones a decision is made from: CML ids, the four
thickness numbers, severities, finding ids. The header fields and the prose
are scored too, but separately -- a misread plant name does not change a
verdict.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from workbench.evidence import CORPUS, HEADER_FIELDS  # noqa: E402
from workbench.scan_reader import from_corpus  # noqa: E402

CRITICAL_READING = ("cml_id", "nominal_mm", "previous_mm", "current_mm", "min_required_mm")
CRITICAL_FINDING = ("finding_id", "severity")
OTHER_READING = ("location",)
OTHER_FINDING = ("location", "description", "ref_clause", "recommendation")


def same(got, want) -> bool:
    """Equal as printed. Numbers compare by value, text after tidying spaces."""
    if want is None:
        return got is None
    if isinstance(want, (int, float)) and not isinstance(want, bool):
        try:
            return got is not None and Decimal(str(got)) == Decimal(str(want))
        except Exception:
            return False
    norm = lambda v: re.sub(r"\s+", " ", str(v or "")).replace("—", "-").replace("–", "-").strip().lower()
    return norm(got) == norm(want)


def score_one(doc_id: str, quality: str | None, work: Path) -> dict:
    truth = json.loads((CORPUS / "truth" / f"{doc_id}.json").read_text(encoding="utf-8"))
    t0 = time.time()
    ev = from_corpus(doc_id, quality, work / doc_id)
    seconds = round(time.time() - t0, 1)

    flagged = bool(ev.problems)
    got_readings = {r.cml_id: r for r in ev.readings}
    got_findings = {f.finding_id: f for f in ev.findings}
    result = {"doc_id": doc_id, "seconds": seconds, "problems": len(ev.problems),
              "critical": {"right": 0, "caught": 0, "wrong": []},
              "other": {"right": 0, "caught": 0, "wrong": []},
              "rows": {"missing": [], "extra": []}}

    def check(kind: str, row: str, field: str, got, want, row_flagged: bool) -> None:
        bucket = result[kind]
        if same(got, want):
            bucket["right"] += 1
        elif row_flagged or flagged:
            bucket["caught"] += 1
        else:
            bucket["wrong"].append(f"{row}.{field}: read {got!r}, printed {want!r}")

    for want in truth["readings"]:
        cml = want["cml_id"]
        got = got_readings.get(cml)
        if got is None:
            result["rows"]["missing"].append(cml)
            continue
        row_flagged = got.review_status == "needs review"
        for f in CRITICAL_READING:
            check("critical", cml, f, getattr(got, f), want.get(f), row_flagged)
        for f in OTHER_READING:
            check("other", cml, f, getattr(got, f), want.get(f), row_flagged)
    result["rows"]["extra"] += sorted(set(got_readings) - {r["cml_id"] for r in truth["readings"]})

    for want in truth["findings"]:
        fid = want["finding_id"]
        got = got_findings.get(fid)
        if got is None:
            result["rows"]["missing"].append(fid)
            continue
        for f in CRITICAL_FINDING:
            check("critical", fid, f, getattr(got, f), want.get(f), False)
        for f in OTHER_FINDING:
            check("other", fid, f, getattr(got, f), want.get(f), False)
    result["rows"]["extra"] += sorted(set(got_findings) - {f["finding_id"] for f in truth["findings"]})

    for f in HEADER_FIELDS:
        check("other", "header", f, ev.header.get(f), truth.get(f), False)

    result["problem_list"] = ev.problems
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("doc_ids", nargs="*", help="default: every report in the corpus index")
    ap.add_argument("--pdf", action="store_true", help="read the born-digital PDFs")
    ap.add_argument("--quality", default="medium", choices=["clean", "light", "medium", "heavy"])
    ap.add_argument("--out", type=Path, default=None, help="write the full result as JSON")
    args = ap.parse_args()

    index = json.loads((CORPUS / "index.json").read_text(encoding="utf-8"))
    doc_ids = args.doc_ids or [e["doc_id"] for e in index]
    quality = None if args.pdf else args.quality
    work = ROOT / "runs" / "_reader_score"
    source = "born-digital PDF (text layer)" if args.pdf else f"{quality} scan (OCR)"
    print(f"reading {len(doc_ids)} report(s) from the {source}\n")

    results, totals = [], {"critical_right": 0, "critical_caught": 0, "critical_wrong": 0,
                           "other_right": 0, "other_caught": 0, "other_wrong": 0}
    for doc_id in doc_ids:
        try:
            r = score_one(doc_id, quality, work)
        except Exception as exc:  # a reader that crashes is a failure, not a gap
            print(f"{doc_id}: CRASHED -- {type(exc).__name__}: {exc}")
            results.append({"doc_id": doc_id, "crashed": f"{type(exc).__name__}: {exc}"})
            continue
        results.append(r)
        totals["critical_right"] += r["critical"]["right"]
        totals["critical_caught"] += r["critical"]["caught"]
        totals["critical_wrong"] += len(r["critical"]["wrong"])
        totals["other_right"] += r["other"]["right"]
        totals["other_caught"] += r["other"]["caught"]
        totals["other_wrong"] += len(r["other"]["wrong"])
        flag = "" if not r["critical"]["wrong"] else "  <-- ACCEPTED WRONG"
        print(f"{doc_id}: {r['seconds']:>5}s  critical {r['critical']['right']} right, "
              f"{r['critical']['caught']} caught, {len(r['critical']['wrong'])} accepted wrong; "
              f"other {len(r['other']['wrong'])} accepted wrong; "
              f"{r['problems']} problem(s){flag}")
        for line in r["critical"]["wrong"] + r["rows"]["missing"] + r["rows"]["extra"]:
            print(f"      {line}")

    n = sum(1 for r in results if "crashed" not in r)
    print(f"\n{n}/{len(doc_ids)} read without crashing")
    print(f"critical fields: {totals['critical_right']} right, {totals['critical_caught']} caught, "
          f"{totals['critical_wrong']} ACCEPTED WRONG")
    print(f"other fields:    {totals['other_right']} right, {totals['other_caught']} caught, "
          f"{totals['other_wrong']} ACCEPTED WRONG")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"source": source, "totals": totals, "reports": results},
                                       indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"written: {args.out}")
    return 1 if totals["critical_wrong"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
