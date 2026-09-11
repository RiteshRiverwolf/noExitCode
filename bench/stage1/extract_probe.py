"""Step 1 probe: can a vision model read an inspection scan into our evidence fields?

    python extract_probe.py <ollama-model> <quality> <doc_id> [<doc_id> ...]

Sends each page listed in index.json to the model with a JSON schema (Ollama
structured output), then compares every field with the ground truth. Numbers
are compared as written (strings), so 20.0 vs 20 or 12.32 vs 12.23 count.
Critical fields = CML ids, all four thickness numbers, severities, finding ids.
"""
import base64, json, re, sys, time
from pathlib import Path
import httpx

ROOT = Path(r"C:\SIH 2026")
CORPUS = ROOT / "data" / "corpus"
OUT = Path(__file__).parent / "extract_results"
OUT.mkdir(exist_ok=True)

S = {"type": "string"}
N = {"type": ["string", "null"]}  # numbers as written on the page
SCHEMA = {
    "type": "object",
    "properties": {
        "report_no": S, "equipment_tag": S, "equipment_name": S, "unit": S, "plant": S,
        "inspection_type": S, "inspection_date": S, "next_due_date": S,
        "inspector_name": S, "inspector_cert": S, "design_pressure_barg": N, "design_temp_c": N,
        "service_fluid": S, "year_built": N, "corrosion_rate_mm_yr": N, "remaining_life_yr": N,
        "findings": {"type": "array", "items": {"type": "object", "properties": {
            "finding_id": S, "location": S, "description": S, "severity": S, "ref_clause": S,
            "recommendation": S},
            "required": ["finding_id", "location", "description", "severity", "ref_clause", "recommendation"]}},
        "readings": {"type": "array", "items": {"type": "object", "properties": {
            "cml_id": S, "location": S, "nominal_mm": N, "previous_mm": N, "current_mm": N,
            "min_required_mm": N, "status": S},
            "required": ["cml_id", "location", "nominal_mm", "previous_mm", "current_mm", "min_required_mm", "status"]}},
    },
    "required": ["report_no", "equipment_tag", "findings", "readings"],
}
PROMPT = (
    "This is a scanned equipment inspection report. Transcribe it into the JSON schema. "
    "Copy every value exactly as printed: do not round, convert, correct or guess. "
    "Numbers: copy the digits as printed, without units (e.g. '15.6' for '15.6 barg'). "
    "Findings come from section 2, with the recommendation for the same Ref from section 4. "
    "Readings come from the ultrasonic thickness survey table, one per CML row. "
    "If a value is unreadable, use null. "
    "Reply with only a JSON object with exactly these keys (no other keys, no markdown):\n"
)
TEMPLATE = (
    '{"report_no": "", "equipment_tag": "", "equipment_name": "", "unit": "", "plant": "", '
    '"inspection_type": "", "inspection_date": "", "next_due_date": "", "inspector_name": "", '
    '"inspector_cert": "", "design_pressure_barg": "", "design_temp_c": "", "service_fluid": "", '
    '"year_built": "", "corrosion_rate_mm_yr": "", "remaining_life_yr": "", '
    '"findings": [{"finding_id": "", "location": "", "description": "", "severity": "", '
    '"ref_clause": "", "recommendation": ""}], '
    '"readings": [{"cml_id": "", "location": "", "nominal_mm": "", "previous_mm": "", '
    '"current_mm": "", "min_required_mm": "", "status": ""}]}'
)
PROMPT += TEMPLATE


def parse(text: str) -> dict:
    """The model's JSON, tolerating fences and {"value": x} wrappers. Keys are not renamed."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
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
HEADER = ["report_no", "equipment_tag", "equipment_name", "unit", "plant", "inspection_type",
          "inspection_date", "next_due_date", "inspector_name", "inspector_cert", "design_pressure_barg",
          "design_temp_c", "service_fluid", "year_built", "corrosion_rate_mm_yr", "remaining_life_yr"]
NUMS = ["nominal_mm", "previous_mm", "current_mm", "min_required_mm"]


def norm(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    s = re.sub("[‐‑‒–—―−]", "-", s)
    s = re.sub(r"\s+", " ", s).replace("°", "deg")
    return s.lower()


def num(v) -> str:
    """Compare numbers by value but keep the printed digits: '20.0' == '20.0', '12.32' != '12.23'."""
    if v is None:
        return ""
    m = re.search(r"-?\d+(?:\.\d+)?", str(v))
    if not m:
        return "?" + str(v)
    s = m.group(0)
    return s.rstrip("0").rstrip(".") if "." in s else s


def score(got: dict, truth: dict) -> dict:
    errs, crit_errs, n, crit_n = [], [], 0, 0
    for k in HEADER:
        n += 1
        a, b = got.get(k), truth.get(k)
        same = num(a) == num(b) if isinstance(b, (int, float)) else norm(a) == norm(b)
        if not same:
            errs.append(f"header.{k}: got {a!r} want {b!r}")
    gf = {f.get("finding_id"): f for f in got.get("findings", [])}
    for f in truth["findings"]:
        g = gf.get(f["finding_id"])
        for k in ["location", "description", "severity", "ref_clause", "recommendation"]:
            n += 1
            crit = k == "severity"
            crit_n += crit
            if g is None or norm(g.get(k)) != norm(f[k]):
                e = f"{f['finding_id']}.{k}: got {None if g is None else g.get(k)!r} want {f[k]!r}"
                errs.append(e)
                if crit:
                    crit_errs.append(e)
    extra_f = sorted(set(gf) - {f["finding_id"] for f in truth["findings"]}, key=str)
    gr = {r.get("cml_id"): r for r in got.get("readings", [])}
    for r in truth["readings"]:
        g = gr.get(r["cml_id"])
        crit_n += 1  # the CML row itself
        if g is None:
            crit_errs.append(f"{r['cml_id']}: missing row")
            errs.append(crit_errs[-1])
            n += 5; crit_n += 4
            continue
        n += 1
        if norm(g.get("location")) != norm(r["location"]):
            errs.append(f"{r['cml_id']}.location: got {g.get('location')!r} want {r['location']!r}")
        for k in NUMS:
            n += 1; crit_n += 1
            if num(g.get(k)) != num(r.get(k)):
                e = f"{r['cml_id']}.{k}: got {g.get(k)!r} want {r.get(k)!r}"
                errs.append(e); crit_errs.append(e)
    extra_r = sorted(set(gr) - {r["cml_id"] for r in truth["readings"]}, key=str)
    if extra_f or extra_r:
        e = f"invented rows: findings {extra_f} readings {extra_r}"
        errs.append(e); crit_errs.append(e)
    return {"fields": n, "errors": len(errs), "critical_fields": crit_n, "critical_errors": len(crit_errs),
            "error_list": errs, "critical_list": crit_errs}


def main():
    model, quality, docs = sys.argv[1], sys.argv[2], sys.argv[3:]
    index = {e["doc_id"]: e for e in json.loads((CORPUS / "index.json").read_text(encoding="utf-8"))}
    summary = []
    for doc in docs:
        pages = [CORPUS / p for p in index[doc]["scans"][quality]]  # the index, not the folder: stale p2 files exist
        truth = json.loads((CORPUS / "truth" / f"{doc}.json").read_text(encoding="utf-8"))
        imgs = [base64.b64encode(p.read_bytes()).decode() for p in pages]
        t = time.time()
        try:
            r = httpx.post("http://127.0.0.1:11434/api/chat", timeout=900, json={
                "model": model, "stream": False, "think": False, "format": SCHEMA,
                "messages": [{"role": "user", "content": PROMPT, "images": imgs}],
                "options": {"temperature": 0, "num_ctx": 16384}})
            body = r.json()
            if "error" in body:
                raise RuntimeError(body["error"])
            got = parse(body["message"]["content"])
            res = score(got, truth)
        except Exception as e:
            msg = body.get("message", {}) if isinstance(body, dict) else {}
            got = {"raw_content": msg.get("content"), "raw_thinking": msg.get("thinking"),
                   "done_reason": body.get("done_reason") if isinstance(body, dict) else None}
            res = {"error": f"{type(e).__name__}: {e} | done_reason={got['done_reason']} "
                            f"content={len(got['raw_content'] or '')}ch thinking={len(got['raw_thinking'] or '')}ch "
                            f"head={(got['raw_content'] or '')[:200]!r}"}
        res.update(doc=doc, model=model, quality=quality, pages=len(pages), seconds=round(time.time() - t, 1),
                   eval_tokens=body.get("eval_count"), prompt_tokens=body.get("prompt_eval_count"))
        safe = re.sub(r"[^\w.-]", "_", model)
        (OUT / f"{doc}_{quality}_{safe}.json").write_text(
            json.dumps({"result": res, "extracted": got}, indent=2, ensure_ascii=False), encoding="utf-8")
        summary.append(res)
        if "error" in res:
            print(f"{doc} {quality}: ERROR {res['error']}")
        else:
            print(f"{doc} {quality}: {res['errors']}/{res['fields']} field errors, "
                  f"{res['critical_errors']}/{res['critical_fields']} critical, {res['seconds']}s, "
                  f"prompt {res['prompt_tokens']} tok")
            for e in res["critical_list"][:8]:
                print("   CRIT", e)
            for e in [x for x in res["error_list"] if x not in res["critical_list"]][:6]:
                print("   minor", e)
    ok = [s for s in summary if "error" not in s]
    if ok:
        print(f"TOTAL {model} {quality}: {sum(s['critical_errors'] for s in ok)}/{sum(s['critical_fields'] for s in ok)}"
              f" critical errors, {sum(s['errors'] for s in ok)}/{sum(s['fields'] for s in ok)} all fields, "
              f"{len(ok)}/{len(summary)} docs parsed")


if __name__ == "__main__":
    main()
