"""Rescore every saved reading with one rule set: locations count as critical.

A reading's location says where on the vessel the thickness was measured, and
a finding's location says where the defect is; an engineer acts on both.
(qwen3.5:9b misread CML-01's location on the clean insp_1002 scan in 4 of 4 runs.)
"""
import json, sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from extract_probe import score, CORPUS

RES = Path(__file__).parent / "extract_results"
rows = defaultdict(lambda: {"docs": 0, "crit": 0, "crit_n": 0, "err": 0, "n": 0, "docs_with_crit": [], "lists": []})
for f in sorted(RES.glob("*.json")):
    d = json.loads(f.read_text(encoding="utf-8"))
    r, got = d["result"], d["extracted"]
    if "error" in r or not got or "raw_content" in got:
        rows[(r["model"], r["quality"])]["lists"].append(f"{r['doc']}: FAILED TO PARSE")
        continue
    truth = json.loads((CORPUS / "truth" / f"{r['doc']}.json").read_text(encoding="utf-8"))
    s = score(got, truth)
    loc = [e for e in s["error_list"] if ".location:" in e]
    crit = s["critical_list"] + loc
    n_loc = len(truth["findings"]) + len(truth["readings"])
    row = rows[(r["model"], r["quality"])]
    row["docs"] += 1
    row["crit"] += len(crit); row["crit_n"] += s["critical_fields"] + n_loc
    row["err"] += s["errors"]; row["n"] += s["fields"]
    if crit:
        row["docs_with_crit"].append(r["doc"])
        row["lists"] += [f"{r['doc']}: {e}" for e in crit]

order = {"clean": 0, "light": 1, "medium": 2, "heavy": 3}
print(f"{'model':14} {'quality':8} {'docs':>4}  {'critical wrong':>16}  {'all fields wrong':>17}  docs with a critical error")
for (m, q), row in sorted(rows.items(), key=lambda kv: (kv[0][0], order.get(kv[0][1], 9))):
    print(f"{m:14} {q:8} {row['docs']:>4}  {row['crit']:>6}/{row['crit_n']:<9}  {row['err']:>6}/{row['n']:<10}  {', '.join(row['docs_with_crit']) or '-'}")
print()
for (m, q), row in sorted(rows.items(), key=lambda kv: (kv[0][0], order.get(kv[0][1], 9))):
    for line in row["lists"]:
        print(f"  [{m} {q}] {line}")
