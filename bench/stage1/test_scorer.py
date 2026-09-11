"""Does the scorer catch real mistakes? Feed it the truth, then deliberately corrupted copies."""
import copy, json, sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from extract_probe import score, CORPUS

truth = json.loads((CORPUS / "truth" / "insp_1002.json").read_text(encoding="utf-8"))


def as_model(t):
    """The truth as a model would return it: numbers as printed strings."""
    g = copy.deepcopy(t)
    for r in g["readings"]:
        for k in ("nominal_mm", "previous_mm", "current_mm", "min_required_mm"):
            r[k] = f"{r[k]:.2f}".rstrip("0").rstrip(".") if r[k] is not None else None
    return g


cases = {}
cases["identical"] = (as_model(truth), 0, 0)
g = as_model(truth); g["readings"][2]["current_mm"] = "12.23"; cases["digit swap 12.32->12.23 (CML-03 current)"] = (g, 1, 1)
g = as_model(truth); g["readings"][2]["current_mm"] = "12.3"; cases["rounded 12.32->12.3"] = (g, 1, 1)
g = as_model(truth); g["readings"][2]["current_mm"], g["readings"][2]["min_required_mm"] = "12.7", "12.32"; cases["current/min columns swapped"] = (g, 2, 2)
g = as_model(truth); del g["readings"][1]; cases["dropped CML-02 row"] = (g, None, 1)
g = as_model(truth); g["readings"].append(dict(g["readings"][0], cml_id="CML-05")); cases["invented CML-05 row"] = (g, 1, 1)
g = as_model(truth); g["findings"][0]["severity"] = "Major"; cases["severity Minor->Major"] = (g, 1, 1)
g = as_model(truth); g["readings"][0], g["readings"][1] = dict(g["readings"][1], cml_id="CML-01"), dict(g["readings"][0], cml_id="CML-02"); cases["row values attached to wrong CML"] = (g, None, 8)
g = as_model(truth); g["readings"][2]["current_mm"] = "12.32 mm"; cases["unit left in (should still match)"] = (g, 0, 0)
g = as_model(truth); g["readings"][2]["current_mm"] = None; cases["unreadable -> null"] = (g, 1, 1)
g = as_model(truth); g["equipment_tag"] = "R-2274"; cases["header tag digits swapped"] = (g, 1, 0)

bad = 0
for name, (g, want_err, want_crit) in cases.items():
    s = score(g, truth)
    ok = (want_err is None or s["errors"] == want_err) and s["critical_errors"] == want_crit
    bad += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {name}: errors {s['errors']} (want {want_err}), critical {s['critical_errors']} (want {want_crit})")
    if not ok:
        for e in s["error_list"]:
            print("        ", e)
print("ALL SCORER TESTS PASS" if not bad else f"{bad} SCORER TEST(S) FAILED")
