"""The dangerous case: a partly unreadable number. Does the reader truncate (12.3), guess (12.32), or say null?

    python partial_test.py make          # images + zoomed crops to check by eye
    python partial_test.py run [model]   # 3 runs per variant

Target: CML-03 current thickness on insp_1002 p1 (printed 12.32; minimum 12.7).
The last glyph is found from the dark pixels in the cell, not from hand-typed coordinates.
Variants: 'erased' (last digit whited out), 'blurred' (last digit heavily blurred).
"""
import base64, json, sys
from pathlib import Path
import httpx
sys.path.insert(0, str(Path(__file__).parent))
from extract_probe import PROMPT, parse, CORPUS

HERE = Path(__file__).parent / "partial"
HERE.mkdir(exist_ok=True)
CELL = (958, 1318, 1102, 1350)  # CML-03 "Current" cell on the clean scan (checked by eye)


def last_glyph(im, cell):
    """Column span of the right-most run of dark pixels in the cell."""
    x0, y0, x1, y1 = cell
    g = im.convert("L")
    dark = [any(g.getpixel((x, y)) < 110 for y in range(y0, y1)) for x in range(x0, x1)]
    xs = [x0 + i for i, d in enumerate(dark) if d]
    right = xs[-1]
    left = right
    while left - 1 >= x0 and dark[left - 1 - x0]:
        left -= 1
    return left - 1, right + 2


def make():
    from PIL import Image, ImageDraw, ImageFilter
    src = Image.open(CORPUS / "scans" / "clean" / "insp_1002_p1.png").convert("RGB")
    gx0, gx1 = last_glyph(src, CELL)
    box = (gx0, CELL[1] + 2, gx1, CELL[3] - 2)
    print("last glyph columns", gx0, gx1)
    erased = src.copy()
    ImageDraw.Draw(erased).rectangle(box, fill="white")
    blurred = src.copy()
    region = blurred.crop(box).filter(ImageFilter.GaussianBlur(4))
    blurred.paste(region, box[:2])
    for name, im in (("erased", erased), ("blurred", blurred)):
        im.save(HERE / f"insp_1002_p1_{name}.png")
        crop = im.crop((CELL[0] - 40, CELL[1] - 10, CELL[2] + 40, CELL[3] + 10))
        crop.resize((crop.width * 4, crop.height * 4)).save(HERE / f"crop_{name}.png")
        print("wrote", name)


def checks(row: dict) -> list[str]:
    """Cheap code checks that need no second reader. Returns the ones that fire."""
    fired = []
    try:
        cur, mn = float(row.get("current_mm")), float(row.get("min_required_mm"))
        status = str(row.get("status") or "").upper()
        if ("BELOW" in status) != (cur < mn):
            fired.append(f"status '{row.get('status')}' contradicts {cur} vs min {mn}")
        prev = row.get("previous_mm")
        if prev not in (None, "") and cur > float(prev):
            fired.append(f"current {cur} > previous {prev} (thickness grew)")
    except (TypeError, ValueError):
        fired.append("value missing or not a number")
    return fired


def run(model, n_hot=5):
    for name in ("erased", "blurred"):
        b64 = base64.b64encode((HERE / f"insp_1002_p1_{name}.png").read_bytes()).decode()
        for i in range(1, n_hot + 2):
            temp = 0 if i == 1 else 0.7
            r = httpx.post("http://127.0.0.1:11434/api/chat", timeout=900, json={
                "model": model, "stream": False, "think": False,
                "messages": [{"role": "user", "content": PROMPT, "images": [b64]}],
                "options": {"temperature": temp, "seed": 100 + i, "num_ctx": 16384}}).json()
            got = parse(r["message"]["content"])
            (HERE / f"{name}_run{i}_{model.replace(':', '_')}.json").write_text(
                json.dumps(got, indent=2, ensure_ascii=False), encoding="utf-8")
            row = next((x for x in got.get("readings", []) if x.get("cml_id") == "CML-03"), {})
            v = row.get("current_mm", "<row missing>")
            kind = ("NULL (good)" if v in (None, "") else "TRUNCATED" if str(v).strip() in ("12.3", "12") else
                    "GUESSED the true value" if str(v).strip() == "12.32" else f"OTHER {v!r}")
            below = kind != "NULL (good)" and not checks(row) or None
            fired = checks(row)
            print(f"{name} run {i} (temp {temp}): CML-03 current={v!r} prev={row.get('previous_mm')!r} "
                  f"min={row.get('min_required_mm')!r} status={row.get('status')!r} -> {kind}; "
                  f"code checks: {fired or 'none fire'}", flush=True)


if __name__ == "__main__":
    make() if sys.argv[1] == "make" else run(sys.argv[2] if len(sys.argv) > 2 else "qwen3.5:9b")
