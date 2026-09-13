"""Does the reference library find the passage that answers each question?

    .venv\\Scripts\\python bench\\stage3\\library_score.py
    .venv\\Scripts\\python bench\\stage3\\library_score.py -k 3 --out results\\stage3\\library_retrieval.json

Retrieval only -- whether the right text reaches the Librarian at all. Whether
the Librarian then answers correctly, cites it, and refuses when it should is
scored separately, because a model can fail with the right passage in front of
it, and a good passage search is worthless if the answer invents a clause.

For each answerable question (bench/library/content.py, QUESTIONS):
    found     at least one expected section, or page, is in the top k
    all hops  every section in `needs` is in the top k -- the multi-document case --
              counted separately when a hop arrived only by following a reference
              ("under SOP-INSP-001 section 2") rather than by the search's own ranking
    rank      where the first expected passage came

For the questions the library cannot answer, nothing is "found". The script
reports how strongly the top passage matched, next to the scores of answerable
questions -- the evidence a refusal threshold would be set from. It does NOT
set one: five unanswerable questions are far too few to fit a threshold to.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from bench.library.content import QUESTIONS  # noqa: E402
from workbench.library import config, search  # noqa: E402


def matches(hit, expect: list, pages: list) -> bool:
    if any(hit.doc_id == d and hit.section == s for d, s in expect):
        return True
    return any(hit.doc_id == d and hit.pages[0] <= p <= hit.pages[1] for d, p in pages)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-k", type=int, default=None, help="default: search.k in workbench/library.yaml")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    args.k = args.k or config()["search"]["k"]

    results, found, hops_ok, hops_search, hops_total = [], 0, 0, 0, 0
    answerable_cos, unanswerable_cos = [], []
    for q in QUESTIONS:
        hits = search(q["question"], k=args.k)
        ranked = [h for h in hits if "referenced_by" not in h.why]      # what the search itself ranked
        top = ranked[0] if ranked else None
        top_cos = top.why.get("cosine") if top else None
        row = {"id": q["id"], "question": q["question"],
               "top": [{"citation": h.citation(), "score": h.score, "why": h.why} for h in hits]}
        if q.get("answerable", True):
            expect, pages = q.get("expect", []), q.get("expect_pages", [])
            ranks = [i + 1 for i, h in enumerate(ranked) if matches(h, expect, pages)]
            row["found_at"] = ranks[0] if ranks else None
            found += bool(ranks)
            if q.get("needs"):
                hops_total += 1
                ok = all(any(h.doc_id == d and h.section == s for h in hits) for d, s in q["needs"])
                by_search = all(any(h.doc_id == d and h.section == s for h in ranked) for d, s in q["needs"])
                row["all_hops"], row["all_hops_by_search"] = ok, by_search
                hops_ok += ok
                hops_search += by_search
            answerable_cos.append(top_cos)
            mark = f"found at {ranks[0]}" if ranks else "NOT FOUND"
            hop = "" if "all_hops" not in row else (
                "  all hops" if row["all_hops_by_search"] else
                "  all hops (ref)" if row["all_hops"] else "  MISSING A HOP")
            print(f"{q['id']}  {mark:12}{hop:17} top: {top.citation() if top else '-':40} cos {top_cos}")
        else:
            unanswerable_cos.append(top_cos)
            print(f"{q['id']}  (unanswerable)              top: {top.citation() if top else '-':40} cos {top_cos}"
                  f"   -- {q['why']}")
        results.append(row)

    n = sum(1 for q in QUESTIONS if q.get("answerable", True))
    print(f"\nfound in the top {args.k}: {found}/{n}   multi-document questions with every hop: "
          f"{hops_ok}/{hops_total} ({hops_search} by search alone, the rest by following a reference)")
    if answerable_cos and unanswerable_cos:
        print(f"top-passage cosine -- answerable: min {min(answerable_cos):.3f}, median "
              f"{statistics.median(answerable_cos):.3f}; unanswerable: max {max(unanswerable_cos):.3f}, "
              f"median {statistics.median(unanswerable_cos):.3f}")
        overlap = max(unanswerable_cos) >= min(answerable_cos)
        print("the two ranges overlap: a similarity threshold alone cannot tell them apart" if overlap
              else "the two ranges do not overlap on these questions -- too few to trust as a threshold")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"k": args.k, "found": found, "answerable": n,
                                        "hops": [hops_ok, hops_total], "questions": results},
                                       indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"written: {args.out}")
    return 0 if found == n else 1


if __name__ == "__main__":
    raise SystemExit(main())
