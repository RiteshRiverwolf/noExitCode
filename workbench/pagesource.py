"""Page source: one document of any length -> per page, text with positions.

Step (1) of the reader (ARCHITECTURE section 7.1, results/stage1/NOTES.md
section 4). Everything downstream -- placing values in table cells, cutting
the crop an engineer checks -- works on one uniform shape, whatever the page
came from:

    TextItem(text, score, bbox, page)   bbox in PIXELS, top-left origin, at DPI
    Page(number, size, items, image_path, read_by)

Two ways in, chosen per page, never guessed globally:

  * **text layer** -- the PDF already holds the characters and their boxes
    (born-digital, which every corpus PDF is: 2,759 characters and no image
    objects on insp_1002 page 1). Reading them is exact and instant, so OCR
    would only add mistakes. Used when the page has at least MIN_CHARS
    characters of real text.
  * **OCR** -- the page is an image (a scan, a photographed page, or an
    image-only PDF). PP-StructureV3 reads it. Its *text* reading is excellent
    (16/16 thickness numbers on every scan quality) but its *table structure*
    is not trusted, so only `overall_ocr_res` -- the page's text lines with
    their boxes and confidence -- is taken. Code places them into cells
    (workbench/tablemap.py).

Both paths also leave a rendered page image behind, because a number is only
really checkable by a person against the picture of the cell it came from.

PaddleOCR lives in a separate environment (`.venv-ocr`; its paddlepaddle
build conflicts with the workbench's dependencies), so OCR runs as a
subprocess of that interpreter -- see ocr_worker.py. Results are cached by
image hash under data/cache/ocr/, since a page takes 130-200 s on the CPU
build.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium

ROOT = Path(__file__).resolve().parent.parent
OCR_PYTHON = Path(os.environ.get("SIH_OCR_PYTHON", ROOT / ".venv-ocr" / "Scripts" / "python.exe"))
OCR_WORKER = Path(__file__).resolve().parent / "ocr_worker.py"
OCR_CACHE = ROOT / "data" / "cache" / "ocr"
DPI = 200                  # the corpus scans are rendered at 200 dpi
MIN_CHARS = 60             # fewer real characters than this: treat the page as an image
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}

TEXT_LAYER = "text layer (pdfium, exact character boxes)"
OCR_READER = "OCR (PP-StructureV3, PaddleOCR 3.7.0)"


@dataclass(frozen=True)
class TextItem:
    """One piece of text with where it sits on the page.

    bbox is (x0, y0, x1, y1) in pixels, top-left origin, at the page's dpi --
    the same frame as image_path, so a crop is a direct .crop(bbox).
    score is 1.0 for the text layer (the characters are the document's own)
    and the recogniser's confidence for OCR.
    """
    text: str
    score: float
    bbox: tuple[float, float, float, float]
    page: int

    @property
    def center(self) -> tuple[float, float]:
        x0, y0, x1, y1 = self.bbox
        return (x0 + x1) / 2, (y0 + y1) / 2


@dataclass
class Page:
    number: int                 # 1-based
    width: int                  # pixels at dpi
    height: int
    dpi: int
    read_by: str                # TEXT_LAYER or OCR_READER -- recorded on every value
    items: list[TextItem]
    image_path: Path            # the page as a picture, for crops
    source_file: str            # path of the document, relative to the repo root


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


# --- the two ways of reading a page -----------------------------------------

def _text_layer_items(page, page_number: int, height_pt: float, scale: float) -> list[TextItem]:
    """The PDF's own characters, in pixel space. pdfium rects are (left, bottom,
    right, top) in points from the bottom-left; the page image counts down from
    the top, so y is flipped here and nowhere else."""
    tp = page.get_textpage()
    items = []
    for i in range(tp.count_rects()):
        left, bottom, right, top = tp.get_rect(i)
        text = tp.get_text_bounded(left, bottom, right, top).strip()
        if not text:
            continue
        items.append(TextItem(
            text=text, score=1.0, page=page_number,
            bbox=(left * scale, (height_pt - top) * scale,
                  right * scale, (height_pt - bottom) * scale)))
    return items


def _ocr_items(record: dict, page_number: int) -> list[TextItem]:
    """The OCR worker's page-level reading (see ocr_worker.py for the shape).
    Its table structure is deliberately not used: on the clean scan
    PP-StructureV3 merged the header with CML-01's row."""
    items = []
    for t in record.get("texts", []):
        text = str(t.get("text", "")).strip()
        if not text:
            continue
        x0, y0, x1, y1 = (float(v) for v in t["bbox"])
        items.append(TextItem(text=text, score=float(t.get("score", 0.0)),
                              bbox=(x0, y0, x1, y1), page=page_number))
    return items


def run_ocr(images: list[Path], use_cache: bool = True) -> dict[Path, dict]:
    """OCR several images in one subprocess of the PaddleOCR environment.

    One call for the whole document: the pipeline takes ~20 s to load, so
    reading pages one subprocess at a time would pay that for every page.
    """
    OCR_CACHE.mkdir(parents=True, exist_ok=True)
    out: dict[Path, dict] = {}
    todo: list[Path] = []
    for img in images:
        cached = OCR_CACHE / f"{sha256_file(img)}.json"
        if use_cache and cached.exists():
            out[img] = json.loads(cached.read_text(encoding="utf-8"))
        else:
            todo.append(img)
    if not todo:
        return out
    if not OCR_PYTHON.exists():
        raise RuntimeError(
            f"OCR environment not found at {OCR_PYTHON}. Set SIH_OCR_PYTHON, or read a "
            f"born-digital PDF instead of a scan.")
    proc = subprocess.run(
        [str(OCR_PYTHON), str(OCR_WORKER), "--cache", str(OCR_CACHE), *[str(p) for p in todo]],
        capture_output=True, text=True, cwd=str(ROOT))
    if proc.returncode != 0:
        raise RuntimeError(f"OCR worker failed ({proc.returncode}):\n{proc.stderr[-2000:]}")
    for img in todo:
        cached = OCR_CACHE / f"{sha256_file(img)}.json"
        if not cached.exists():
            raise RuntimeError(f"OCR worker returned no result for {img}")
        out[img] = json.loads(cached.read_text(encoding="utf-8"))
    return out


# --- opening a document ------------------------------------------------------

def _render_pdf_pages(pdf_path: Path, work_dir: Path, dpi: int) -> list[tuple[Path, int]]:
    """Every page as a picture; also how many real characters it holds."""
    work_dir.mkdir(parents=True, exist_ok=True)
    rendered = []
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        for i in range(len(doc)):
            page = doc[i]
            image_path = work_dir / f"{pdf_path.stem}_p{i + 1}.png"
            if not image_path.exists():
                page.render(scale=dpi / 72).to_pil().save(image_path)
            rendered.append((image_path, page.get_textpage().count_chars()))
    finally:
        doc.close()
    return rendered


def open_document(path: Path | str, work_dir: Path, dpi: int = DPI,
                  force: str | None = None) -> list[Page]:
    """Read a PDF (any length) or a page image into Pages.

    force="ocr" reads even a born-digital PDF by OCR -- used to compare the two
    readings of the same page; force="text" refuses to fall back to OCR.
    """
    path = Path(path)
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    if path.suffix.lower() in IMAGE_SUFFIXES:
        results = run_ocr([path])
        from PIL import Image
        with Image.open(path) as im:
            size = im.size
        return [Page(number=1, width=size[0], height=size[1], dpi=dpi, read_by=OCR_READER,
                     items=_ocr_items(results[path], 1), image_path=path,
                     source_file=_rel(path))]

    if path.suffix.lower() != ".pdf":
        raise ValueError(f"not a PDF or a page image: {path}")

    rendered = _render_pdf_pages(path, work_dir, dpi)
    doc = pdfium.PdfDocument(str(path))
    try:
        by_ocr = [n for n, (_, chars) in enumerate(rendered, 1)
                  if force == "ocr" or (force != "text" and chars < MIN_CHARS)]
        ocr_results = run_ocr([rendered[n - 1][0] for n in by_ocr]) if by_ocr else {}
        pages = []
        for i, (image_path, chars) in enumerate(rendered):
            number = i + 1
            pdf_page = doc[i]
            w_pt, h_pt = pdf_page.get_size()
            scale = dpi / 72
            if number in by_ocr:
                items, read_by = _ocr_items(ocr_results[image_path], number), OCR_READER
            else:
                items, read_by = _text_layer_items(pdf_page, number, h_pt, scale), TEXT_LAYER
            pages.append(Page(number=number, width=round(w_pt * scale), height=round(h_pt * scale),
                              dpi=dpi, read_by=read_by, items=items, image_path=image_path,
                              source_file=_rel(path)))
        return pages
    finally:
        doc.close()


def open_pages(paths: list[Path | str], work_dir: Path, dpi: int = DPI) -> list[Page]:
    """Several page images that together make one document (the corpus scans).

    They are OCR'd in one subprocess and renumbered 1..n in the order given --
    the order comes from the corpus index, never from a folder listing (the
    scan folders once held stale pages from an older build).
    """
    paths = [Path(p) for p in paths]
    results = run_ocr(paths)
    from PIL import Image
    pages = []
    for i, p in enumerate(paths):
        with Image.open(p) as im:
            size = im.size
        pages.append(Page(number=i + 1, width=size[0], height=size[1], dpi=DPI, read_by=OCR_READER,
                          items=_ocr_items(results[p], i + 1), image_path=p, source_file=_rel(p)))
    return pages


if __name__ == "__main__":  # a quick look at what a document reads as
    work = ROOT / "runs" / "_pagesource_probe"
    for arg in sys.argv[1:]:
        for page in open_document(arg, work):
            print(f"{page.source_file} p{page.number}: {page.width}x{page.height}px, "
                  f"{len(page.items)} items, {page.read_by}")
            for it in page.items[:8]:
                print(f"    {it.text[:48]!r:52} {it.score:.3f} {[round(v) for v in it.bbox]}")
