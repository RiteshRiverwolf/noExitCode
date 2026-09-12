"""Does the reader catch a damaged digit, or quietly write a plausible number?

    .venv\\Scripts\\python bench\\stage2\\damaged_cell_test.py

The stage-1 finding this exists to answer (results/stage1/NOTES.md sections 2
and 3): the last digit of CML-03's current thickness, the breached reading
12.32, was smudged and then erased on insp_1002's clean scan.

    qwen3.5:9b reading the whole page   wrote "12.3" in 13 of 18 reads, and
                                        another cell's value in 3 -- each of
                                        which turns ESCALATE into NO TRIGGER
    PP-StructureV3                      read "12.3" at confidence 1.000

Both readers produce a clean, wrong, *decision-changing* number and neither
says anything is wrong. Confidence does not catch it. The question here is
only whether the reader now RAISES THE CELL FOR REVIEW -- not whether it can
recover the lost digit, which nothing can.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from workbench.pagesource import open_pages  # noqa: E402
from workbench.scan_reader import build_evidence  # noqa: E402

PRINTED = "12.32"          # what the undamaged page says
CASES = {
    "undamaged (clean scan)": ROOT / "data/corpus/scans/clean/insp_1002_p1.png",
    "last digit blurred": ROOT / "bench/stage1/partial/insp_1002_p1_blurred.png",
    "last digit erased": ROOT / "bench/stage1/partial/insp_1002_p1_erased.png",
}


def main() -> int:
    work = ROOT / "runs" / "_damaged"
    worst = 0
    for name, image in CASES.items():
        if not image.exists():
            print(f"{name}: image missing ({image}) -- skipped")
            continue
        pages = open_pages([image], work)
        ev = build_evidence("insp_1002", pages, crop_dir=work / "crops")
        row = next((r for r in ev.readings if r.cml_id == "CML-03"), None)
        if row is None:
            print(f"{name}: CML-03 was not read at all -> the pipeline stops")
            continue
        value = str(row.current_mm) if row.current_mm is not None else None
        # Only a flag on THIS cell counts. A complaint about the row's location
        # column says nothing about the thickness that drives the decision --
        # counting it would let the test pass while the wrong number goes through.
        flags = [p for p in ev.problems if p.startswith("CML-03.current")]
        right = value == PRINTED
        if right:
            verdict = "read correctly"
        elif flags or row.review_status == "needs review":
            verdict = "WRONG, and raised for review"
        else:
            verdict = "WRONG, AND ACCEPTED SILENTLY"
            worst = 1
        print(f"\n{name}")
        print(f"  CML-03 current read as {value!r} (printed {PRINTED!r}) -> {verdict}")
        print(f"  review status: {row.review_status}")
        for f in flags:
            print(f"  flag: {f}")
        if row.source.crop:
            print(f"  crop for the engineer: {row.source.crop}")
    print("\nA lost digit cannot be recovered by any reader. The only safe "
          "outcome is that the cell reaches a person, with its picture.")
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
