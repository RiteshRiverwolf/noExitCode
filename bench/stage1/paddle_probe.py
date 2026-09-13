"""First look at PaddleOCR-VL-1.6 on a full scan page, through llama-server's OpenAI API.

    python paddle_probe.py <doc_id> <quality> [prompt ...]

Sends one page with each task prompt the model card lists and saves the raw
output. Exploratory: the model is built to read layout crops from PaddleOCR's
pipeline, so a full page may be outside its comfort zone -- that is what this finds out.
"""
import base64, json, sys, time
from pathlib import Path
import httpx

sys.path.insert(0, str(Path(__file__).parent))
from extract_probe import CORPUS

OUT = Path(__file__).parent / "paddle_results"
OUT.mkdir(exist_ok=True)
URL = "http://127.0.0.1:8081/v1/chat/completions"

doc, quality = sys.argv[1], sys.argv[2]
prompts = sys.argv[3:] or ["OCR:", "Table Recognition:", "Spotting:"]
index = {e["doc_id"]: e for e in json.loads((CORPUS / "index.json").read_text(encoding="utf-8"))}
page = CORPUS / index[doc]["scans"][quality][0]
b64 = base64.b64encode(page.read_bytes()).decode()
for p in prompts:
    t = time.time()
    try:
        r = httpx.post(URL, timeout=600, json={
            "temperature": 0, "max_tokens": 6000,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": p}]}]}).json()
        text = r["choices"][0]["message"]["content"] if "choices" in r else json.dumps(r)
        usage = r.get("usage", {})
    except Exception as e:
        text, usage = f"ERROR {type(e).__name__}: {e}", {}
    secs = round(time.time() - t, 1)
    name = p.strip(":").replace(" ", "_").lower()
    (OUT / f"{doc}_{quality}_{name}.txt").write_text(text, encoding="utf-8")
    print(f"=== {p}  {secs}s  usage={usage}  chars={len(text)}")
    print(text[:1500])
    print()
