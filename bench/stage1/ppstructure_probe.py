"""First look at PP-StructureV3 (OCR + table structure) on our scans. Run with .venv-ocr.

    .venv-ocr\\Scripts\\python ppstructure_probe.py

For each image: save the full JSON result, then print every recognised text in
the thickness-survey table with its confidence score and box, so we can see
(a) whether cells come out whole and in the right row, and (b) what the
engine does with the erased and blurred digit -- low confidence, or a clean
wrong number.
"""
import json, sys, time
from pathlib import Path

SP = Path(__file__).parent
CORPUS = Path(r"C:\SIH 2026\data\corpus")
OUT = SP / "ppstructure"
OUT.mkdir(exist_ok=True)
IMAGES = {
    "clean": CORPUS / "scans/clean/insp_1002_p1.png",
    "medium": CORPUS / "scans/medium/insp_1002_p1.png",
    "heavy": CORPUS / "scans/heavy/insp_1002_p1.png",
    "erased": SP / "partial/insp_1002_p1_erased.png",
    "blurred": SP / "partial/insp_1002_p1_blurred.png",
}
only = sys.argv[1:] or list(IMAGES)

from paddleocr import PPStructureV3  # noqa: E402  (slow import; after arg handling)

t = time.time()
pipe = PPStructureV3(
    device="cpu",
    # paddlepaddle 3.3.0 CPU on Windows: the oneDNN path fails in layout detection with
    # "ConvertPirAttribute2RuntimeAttribute not support [pir::ArrayAttribute<pir::DoubleAttribute>]".
    enable_mkldnn=False,
    use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False,
    use_seal_recognition=False, use_formula_recognition=False, use_chart_recognition=False,
    use_table_recognition=True,
)
print(f"pipeline ready in {time.time() - t:.1f}s", flush=True)

for name in only:
    img = IMAGES[name]
    t = time.time()
    res = list(pipe.predict(str(img)))[0]
    secs = time.time() - t
    folder = OUT / name
    folder.mkdir(exist_ok=True)
    res.save_to_json(save_path=str(folder))
    res.save_to_markdown(save_path=str(folder))
    data = json.loads(next(folder.glob("*.json")).read_text(encoding="utf-8"))
    tables = data.get("table_res_list", [])
    print(f"\n=== {name}: {secs:.1f}s, {len(tables)} table(s); top-level keys {sorted(data)}", flush=True)
    for ti, tab in enumerate(tables):
        ocr = tab.get("table_ocr_pred", {})
        texts, scores, boxes = ocr.get("rec_texts", []), ocr.get("rec_scores", []), ocr.get("rec_boxes", [])
        head = " ".join(texts[:6])
        print(f"  table {ti}: {len(tab.get('cell_box_list', []))} cells, {len(texts)} texts; starts: {head[:80]!r}")
        if not any("CML" in x for x in texts):
            continue
        for x, s, b in zip(texts, scores, boxes):
            flag = "  <-- LOW" if s < 0.9 else ""
            print(f"      {x!r:34} score {s:.3f}  box {[int(v) for v in b]}{flag}")
