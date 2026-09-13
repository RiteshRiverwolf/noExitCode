"""OCR one or more page images with PP-StructureV3. Runs in `.venv-ocr`.

    .venv-ocr\\Scripts\\python workbench\\ocr_worker.py --cache data\\cache\\ocr page.png ...

Started as a subprocess by workbench/pagesource.py, never imported by the
workbench: PaddleOCR's paddlepaddle build is kept in its own environment. It
writes one small JSON per image, named by the image's sha256, holding just the
page-level reading the workbench uses:

    {"file", "sha256", "width", "height", "seconds", "engine",
     "texts": [{"text", "score", "bbox": [x0, y0, x1, y1]}]}

The table structure PP-StructureV3 also produces is left out on purpose: it
merged the header with CML-01's row even on a clean scan, so code places the
values by position instead (workbench/tablemap.py).

Settings that are not optional here:
  enable_mkldnn=False            paddlepaddle 3.3.0 CPU on Windows fails in
                                 layout detection with oneDNN
  PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK   no network check at start-up; on the
                                 air-gapped machine the ten models are copied
                                 into ~/.paddlex/official_models beforehand
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

ENGINE = "PP-StructureV3 (PaddleOCR 3.7.0)"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("images", nargs="+", type=Path)
    ap.add_argument("--cache", type=Path, required=True, help="folder for <sha256>.json results")
    ap.add_argument("--device", default=os.environ.get("SIH_OCR_DEVICE", "cpu"),
                    help="cpu, or gpu:0 with the paddlepaddle-gpu build")
    args = ap.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)

    from paddleocr import PPStructureV3  # slow import: after the arguments are checked

    t0 = time.time()
    pipe = PPStructureV3(
        device=args.device,
        enable_mkldnn=False,
        use_doc_orientation_classify=False, use_doc_unwarping=False,
        use_textline_orientation=False, use_seal_recognition=False,
        use_formula_recognition=False, use_chart_recognition=False,
        use_table_recognition=False,   # its table structure is not used
    )
    print(f"pipeline ready in {time.time() - t0:.1f}s on {args.device}", flush=True)

    for image in args.images:
        t = time.time()
        result = list(pipe.predict(str(image)))[0]
        with tempfile.TemporaryDirectory() as tmp:
            result.save_to_json(save_path=tmp)
            data = json.loads(next(Path(tmp).glob("*.json")).read_text(encoding="utf-8"))
        ocr = data.get("overall_ocr_res") or {}
        texts = [
            {"text": str(text).strip(), "score": float(score),
             "bbox": [float(v) for v in box]}
            for text, score, box in zip(ocr.get("rec_texts", []), ocr.get("rec_scores", []),
                                        ocr.get("rec_boxes", []))
            if str(text).strip()
        ]
        record = {
            "file": str(image), "sha256": sha256_file(image),
            "width": data.get("width"), "height": data.get("height"),
            "seconds": round(time.time() - t, 1), "engine": ENGINE, "device": args.device,
            "texts": texts,
        }
        (args.cache / f"{record['sha256']}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{image.name}: {len(texts)} texts in {record['seconds']}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
