"""Does the reader guess? White out cells on a scan and see whether it says null or invents a value.

    python occlusion_test.py make          # write the occluded images (check them by eye first)
    python occlusion_test.py run [model]   # read them, 3 runs each, report per cell

Cells (insp_1002 page 1, clean scan, original pixel coordinates):
  CML-03 current (12.32 -- the breached reading), CML-01 min required (12.7),
  F-02 severity (Minor).
A second image whites out the same cells on the *medium* scan.
"""
import base64, json, sys
from pathlib import Path
import httpx
sys.path.insert(0, str(Path(__file__).parent))
from extract_probe import PROMPT, parse, CORPUS

HERE = Path(__file__).parent / "occlusion"
HERE.mkdir(exist_ok=True)
BOXES = {  # clean scan, 1654 x 2339
    "CML-03.current_mm": (958, 1318, 1102, 1350),
    "CML-01.min_required_mm": (1112, 1236, 1257, 1270),
    "F-02.severity": (1084, 826, 1243, 912),
}


def make():
    from PIL import Image, ImageDraw
    for q in ("clean", "medium"):
        src = CORPUS / "scans" / q / "insp_1002_p1.png"
        im = Image.open(src).convert("RGB")
        sx, sy = im.width / 1654, im.height / 2339  # the noisy scans are slightly different sizes
        d = ImageDraw.Draw(im)
        for box in BOXES.values():
            x0, y0, x1, y1 = box
            d.rectangle((x0 * sx, y0 * sy, x1 * sx, y1 * sy), fill="white")
        out = HERE / f"insp_1002_p1_{q}_occluded.png"
        im.save(out)
        print("wrote", out, im.size)


def pick(got, key):
    row, field = key.split(".")
    items = got.get("readings", []) + got.get("findings", [])
    for it in items:
        if it.get("cml_id") == row or it.get("finding_id") == row:
            return it.get(field)
    return "<row missing>"


def run(model):
    for q in ("clean", "medium"):
        img = HERE / f"insp_1002_p1_{q}_occluded.png"
        b64 = base64.b64encode(img.read_bytes()).decode()
        for i in range(1, 4):
            r = httpx.post("http://127.0.0.1:11434/api/chat", timeout=900, json={
                "model": model, "stream": False, "think": False,
                "messages": [{"role": "user", "content": PROMPT, "images": [b64]}],
                "options": {"temperature": 0 if i == 1 else 0.7, "seed": i, "num_ctx": 16384}}).json()
            got = parse(r["message"]["content"])
            cells = {k: pick(got, k) for k in BOXES}
            verdict = {k: ("NULL/blank (good)" if v in (None, "", "null") else f"INVENTED {v!r}") for k, v in cells.items()}
            print(f"{q} run {i} (temp {0 if i == 1 else 0.7}): {json.dumps(verdict)}")
            (HERE / f"{q}_run{i}_{model.replace(':', '_')}.json").write_text(
                json.dumps({"cells": cells, "extracted": got}, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    make() if sys.argv[1] == "make" else run(sys.argv[2] if len(sys.argv) > 2 else "qwen3.5:9b")
