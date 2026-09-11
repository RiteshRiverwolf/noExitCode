"""Place PP-StructureV3's OCR texts into the thickness table by position -- code, no model.

    python geometry_mapper.py clean medium heavy erased blurred

PP-StructureV3's own table structure (pred_html, cell_box_list) merged the
header with CML-01's row on the clean scan, so it is not trusted. Instead:
  tilt    = slope of the header words (scans are rotated a little); every box
            is straightened by it before rows are assigned;
  columns = where the header words sit (values are left-aligned under them);
  rows    = where the CML ids sit (nearest id, within half a row height).
Checks, all code:
  - exactly one text per cell; numbers parse exactly as printed;
  - OCR confidence >= MIN_SCORE;
  - LEFTOVER INK: dark pixels inside a number cell that no recognised text
    box covers -- a smudged or unread character. PP-StructureV3 read the
    blurred "12.32" as "12.3" at confidence 1.000, so confidence alone
    cannot catch it.
Scored against the ground truth, with one special category: ACCEPTED BUT
WRONG -- a value that passed every check and is not what was printed.
"""
import json, re, statistics, sys
from pathlib import Path

from PIL import Image

SP = Path(__file__).parent
TRUTH = json.loads((Path(r"C:\SIH 2026\data\corpus\truth") / "insp_1002.json").read_text(encoding="utf-8"))
COLS = {"cml": "cml_id", "location": "location", "nominal": "nominal_mm", "previous": "previous_mm",
        "current": "current_mm", "minreq": "min_required_mm", "status": "status"}
NUMERIC = ("nominal_mm", "previous_mm", "current_mm", "min_required_mm")
MIN_SCORE = 0.95
DARK = 140          # grey level below which a pixel counts as ink
EXACT = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*$")
CML = re.compile(r"^CML-\d+$")


def key(text: str) -> str:
    return re.sub(r"[\s.]", "", text).lower()


def table_items(data):
    for t in data.get("table_res_list", []):
        o = t["table_ocr_pred"]
        if any(CML.match(x.strip()) for x in o["rec_texts"]):
            return [(x.strip(), s, [float(v) for v in b]) for x, s, b in
                    zip(o["rec_texts"], o["rec_scores"], o["rec_boxes"])]
    return []


def center(b):
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def map_rows(items):
    heads = {COLS[key(x)]: b for x, s, b in items if key(x) in COLS}
    if len(heads) < len(COLS):
        return None, f"header words found: {sorted(heads)}"
    # Tilt: least-squares slope of header centres (y against x).
    pts = [center(b) for b in heads.values()]
    mx, my = statistics.mean(p[0] for p in pts), statistics.mean(p[1] for p in pts)
    slope = sum((x - mx) * (y - my) for x, y in pts) / sum((x - mx) ** 2 for x, _ in pts)
    straight = lambda b: center(b)[1] - slope * (center(b)[0] - mx)
    col_x = sorted((b[0], name) for name, b in heads.items())
    header_bottom = max(straight(b) for b in heads.values()) + 12
    anchors = sorted((straight(b), x) for x, s, b in items if CML.match(x))
    gaps = [b[0] - a[0] for a, b in zip(anchors, anchors[1:])]
    row_h = statistics.median(gaps) if gaps else 40
    rows = {cml: {c: [] for c in COLS.values()} for _, cml in anchors}
    for x, s, b in items:
        cy = straight(b)
        if cy <= header_bottom:
            continue
        near = min(anchors, key=lambda a: abs(a[0] - cy))
        if abs(near[0] - cy) > row_h / 2:
            continue  # below the table body (corrosion-rate row etc.)
        col = [name for x0, name in col_x if x0 <= b[0] + 12]
        if col:
            rows[near[1]][col[-1]].append((x, s, b))
    geom = {"slope": slope, "mx": mx, "row_h": row_h, "col_x": col_x,
            "anchor_y": {cml: y for y, cml in anchors}}
    return (rows, geom), None


def leftover_ink(img, geom, cml, col, texts):
    """Dark pixels in the cell's area that no recognised text box covers."""
    names = [n for _, n in geom["col_x"]]
    i = names.index(col)
    x0 = geom["col_x"][i][0] - 4
    x1 = geom["col_x"][i + 1][0] - 10 if i + 1 < len(names) else x0 + 140
    half = geom["row_h"] * 0.32
    boxes = [b for _, _, b in texts]
    count = 0
    for x in range(int(x0), int(x1)):
        yc = geom["anchor_y"][cml] + geom["slope"] * (x - geom["mx"])
        for y in range(int(yc - half), int(yc + half)):
            if any(b[0] - 3 <= x <= b[2] + 3 and b[1] - 3 <= y <= b[3] + 3 for b in boxes):
                continue
            if img.getpixel((x, y)) < DARK:
                count += 1
    return count


def evaluate(rows, geom, img):
    truth = {r["cml_id"]: r for r in TRUTH["readings"]}
    cells = []
    for cml, row in rows.items():
        for col in NUMERIC + ("location",):
            got = row[col]
            ink = leftover_ink(img, geom, cml, col, got) if col in NUMERIC else None
            cells.append((cml, col, got, ink))
    inks = sorted(c[3] for c in cells if c[3] is not None)
    # Threshold from this page: well above the typical cell's background speckle.
    ink_limit = max(15, 4 * statistics.median(inks)) if inks else 15
    out, review, silent, wrong = [], [], [], []
    for cml, col, got, ink in cells:
        t = truth.get(cml)
        flags = []
        value, score = (got[0][0], got[0][1]) if len(got) == 1 else (None, None)
        if len(got) != 1:
            flags.append(f"{len(got)} texts in the cell")
        elif col in NUMERIC:
            if not EXACT.match(value):
                flags.append(f"not a number as printed ({value!r})")
            if score < MIN_SCORE:
                flags.append(f"low confidence {score:.3f}")
        if ink is not None and ink > ink_limit:
            flags.append(f"leftover ink: {ink} px")
        want = t[col] if t else None
        if col in NUMERIC:
            ok = value is not None and bool(EXACT.match(value)) and float(value) == float(want)
        else:
            norm = lambda v: re.sub(r"\s*[—–-]\s*", " - ", str(v or "")).strip().lower()
            ok = norm(value) == norm(want)
        line = (f"  {cml}.{col:16} {value!r:26} score {'-' if score is None else f'{score:.3f}'}"
                f"  ink {'-' if ink is None else ink}")
        if flags:
            review.append(f"{cml}.{col}: {'; '.join(flags)}")
            line += f"  REVIEW ({'; '.join(flags)})"
        if not ok:
            wrong.append(f"{cml}.{col}")
            if flags:
                line += "  (wrong, but caught)"
            else:
                silent.append(f"{cml}.{col}: got {value!r} want {want!r}")
                line += "  <-- ACCEPTED BUT WRONG"
        out.append(line)
    missing = sorted(set(truth) - set(rows))
    return out, review, silent, wrong, missing, ink_limit, inks


for name in sys.argv[1:] or ["clean", "medium", "heavy", "erased", "blurred"]:
    files = list((SP / "ppstructure" / name).glob("*.json"))
    if not files:
        print(f"=== {name}: no result yet")
        continue
    data = json.loads(files[0].read_text(encoding="utf-8"))
    mapped, err = map_rows(table_items(data))
    if err:
        print(f"=== {name}: could not map ({err}) -> NEEDS REVIEW")
        continue
    rows, geom = mapped
    img = Image.open(data["input_path"]).convert("L")
    lines, review, silent, wrong, missing, limit, inks = evaluate(rows, geom, img)
    print(f"=== {name}: tilt {geom['slope']:+.4f}; rows {list(rows)}; missing {missing or 'none'}; "
          f"{len(wrong)} wrong ({len(wrong) - len(silent)} caught), {len(silent)} ACCEPTED BUT WRONG, "
          f"{len(review)} sent to review; ink limit {limit:.0f}px (cell inks {inks})")
    for line in lines:
        if "REVIEW" in line or "WRONG" in line or "CML-03.current" in line:
            print(line)
