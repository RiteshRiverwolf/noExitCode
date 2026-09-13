"""OCR every corpus scan that is not cached yet, most informative qualities first.

    .venv\\Scripts\\python bench\\stage2\\ocr_corpus.py            # everything missing
    .venv\\Scripts\\python bench\\stage2\\ocr_corpus.py --dry-run  # just count

PP-StructureV3 on the CPU build takes 130-200 s a page, so the whole corpus is
a couple of hours. It runs in small batches, and each page is cached the moment
it is read, so a run that is stopped part-way still leaves usable results --
which is why medium and heavy go first: they are the qualities that tell us
most, and the ones the scorer is least likely to get right.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from workbench.evidence import CORPUS  # noqa: E402
from workbench.pagesource import OCR_CACHE, run_ocr, sha256_file  # noqa: E402

ORDER = ("medium", "heavy", "clean", "light")
BATCH = 4          # pages per worker process: each process pays ~20 s to load the pipeline


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    index = json.loads((CORPUS / "index.json").read_text(encoding="utf-8"))
    todo: list[Path] = []
    for quality in ORDER:
        for entry in index:
            for rel in entry["scans"][quality]:
                path = CORPUS / rel
                if not (OCR_CACHE / f"{sha256_file(path)}.json").exists():
                    todo.append(path)
    print(f"{len(todo)} page(s) to OCR", flush=True)
    if args.dry_run or not todo:
        return 0

    t0 = time.time()
    done = 0
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        try:
            run_ocr(batch)
            done += len(batch)
        except Exception as e:  # one bad batch does not stop the rest
            print(f"batch failed ({type(e).__name__}): {str(e)[:300]}", flush=True)
        elapsed = time.time() - t0
        per_page = elapsed / max(done, 1)
        print(f"{done}/{len(todo)} pages  {elapsed / 60:.1f} min  "
              f"~{per_page * (len(todo) - done) / 60:.0f} min left  "
              f"(last: {', '.join(p.parent.name + '/' + p.name for p in batch)})", flush=True)
    print(f"finished: {done}/{len(todo)} pages in {(time.time() - t0) / 60:.1f} min", flush=True)
    return 0 if done == len(todo) else 1


if __name__ == "__main__":
    raise SystemExit(main())
