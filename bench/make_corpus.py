"""Build the synthetic inspection-report corpus.

    python bench/make_corpus.py --count 12 --out data/corpus

Produces, per report:
    pdf/<id>.pdf                  born-digital source
    truth/<id>.json               field-level ground truth
    scans/<profile>/<id>_p1.png   degraded renders across the quality curve

The ground-truth sidecar is the point. It is what turns "the OCR looked okay"
into a number.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bench.corpus import PROFILES, degrade_pdf, generate_report, render_report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--count", type=int, default=12, help="reports to generate")
    ap.add_argument("--out", type=Path, default=Path("data/corpus"))
    ap.add_argument("--seed", type=int, default=1000, help="base seed")
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument(
        "--profiles",
        nargs="*",
        default=list(PROFILES),
        help=f"scan profiles: {' '.join(PROFILES)}",
    )
    args = ap.parse_args()

    pdf_dir = args.out / "pdf"
    truth_dir = args.out / "truth"
    scan_dir = args.out / "scans"
    for d in (pdf_dir, truth_dir, scan_dir):
        d.mkdir(parents=True, exist_ok=True)

    # Balanced by construction. An unbalanced corpus lets a model score well by
    # always guessing the majority class, which tells us nothing. Escalating
    # cases are spread across all three triggers so "thickness_only" -- where
    # the findings table looks routine -- is properly represented.
    # Also varied: whether the inspector's summary states the conclusion. A
    # score measured only on leaking summaries would badly overstate real
    # capability, since the agent could read the verdict off one sentence.
    triggers = ["severity", "thickness_only", "both"]
    plan: list[tuple[bool, str | None, bool]] = []
    for i in range(args.count):
        escalate = i % 2 == 0
        leaks = (i // 2) % 2 == 0
        trigger = triggers[(i // 2) % len(triggers)] if escalate else None
        plan.append((escalate, trigger, leaks))

    index = []
    for i in range(args.count):
        seed = args.seed + i
        escalate, trigger, leaks = plan[i]
        report = generate_report(
            seed, escalate=escalate, trigger=trigger, summary_leaks=leaks
        )
        doc_id = f"insp_{seed}"

        pdf_path = render_report(report, pdf_dir / f"{doc_id}.pdf")

        truth = report.to_ground_truth()
        truth["doc_id"] = doc_id
        truth["seed"] = seed
        truth["pdf"] = str(pdf_path.relative_to(args.out)).replace("\\", "/")
        (truth_dir / f"{doc_id}.json").write_text(
            json.dumps(truth, indent=2), encoding="utf-8"
        )

        written = degrade_pdf(
            pdf_path, scan_dir, profiles=args.profiles, dpi=args.dpi, seed=seed
        )

        index.append({
            "doc_id": doc_id,
            "equipment_tag": report.equipment_tag,
            "highest_severity": report.highest_severity,
            "requires_approval": report.requires_approval,
            "approval_reason": report.approval_reason,
            "summary_leaks_conclusion": report.summary_leaks_conclusion,
            "breached_cmls": report.breached_cmls,
            "findings": len(report.findings),
            "scans": {
                k: [str(p.relative_to(args.out)).replace("\\", "/") for p in v]
                for k, v in written.items()
            },
        })
        print(
            f"  {doc_id}  {report.equipment_tag:<8} "
            f"{report.highest_severity:<12} "
            f"{len(report.findings)} findings  "
            f"{'ESCALATE' if report.requires_approval else 'routine':<9} "
            f"{report.approval_reason:<22} "
            f"breach={report.breached_cmls or '-'}"
        )

    (args.out / "index.json").write_text(
        json.dumps(index, indent=2), encoding="utf-8"
    )

    n_esc = sum(1 for r in index if r["requires_approval"])
    print(
        f"\n{len(index)} reports -> {args.out}\n"
        f"  escalation required : {n_esc}\n"
        f"  routine             : {len(index) - n_esc}\n"
        f"  scan profiles       : {', '.join(args.profiles)}\n"
        f"\nA useful corpus needs both classes -- if the split is lopsided, "
        f"vary --seed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
