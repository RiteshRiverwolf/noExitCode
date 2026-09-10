"""Simulate scanning artefacts so OCR is scored against a difficulty curve.

A single "scanned-looking" quality level tells you almost nothing. Four graded
levels tell you where a given OCR engine falls over, which is the actual useful
measurement.

PIL + numpy only -- no OpenCV dependency, so this stays installable everywhere.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
from PIL import Image, ImageEnhance, ImageFilter


@dataclass(frozen=True)
class DegradeProfile:
    """One point on the scan-quality curve."""

    name: str
    skew_deg: float          # max absolute rotation
    blur_radius: float       # gaussian blur sigma
    noise_sigma: float       # additive gaussian noise, 0-255 scale
    jpeg_quality: int        # 100 = no JPEG artefacts
    contrast: float          # 1.0 = unchanged
    brightness: float        # 1.0 = unchanged
    speck_rate: float        # fraction of pixels turned into specks


PROFILES: dict[str, DegradeProfile] = {
    # Born-digital PDF render. The ceiling -- any OCR failure here is the
    # engine's fault, not the image's.
    "clean": DegradeProfile("clean", 0.0, 0.0, 0.0, 100, 1.0, 1.0, 0.0),
    # A good office scanner, well-fed page.
    "light": DegradeProfile("light", 0.35, 0.4, 3.0, 92, 1.04, 1.01, 0.00005),
    # Realistic: slightly skewed feed, mid-range scanner, JPEG in the pipeline.
    "medium": DegradeProfile("medium", 1.1, 0.8, 8.0, 75, 1.12, 0.97, 0.0003),
    # A photocopy of a fax of a printout. The case that breaks things.
    "heavy": DegradeProfile("heavy", 2.4, 1.4, 16.0, 55, 1.25, 0.92, 0.0012),
}


def pdf_to_images(pdf_path: Path, dpi: int = 200) -> list[Image.Image]:
    """Render every page of a PDF to a PIL image."""
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        scale = dpi / 72.0
        return [
            doc[i].render(scale=scale).to_pil().convert("RGB")
            for i in range(len(doc))
        ]
    finally:
        doc.close()


def _add_specks(arr: np.ndarray, rate: float, rng: np.random.Generator) -> np.ndarray:
    """Dust and toner specks -- the thing that produces spurious characters."""
    if rate <= 0:
        return arr
    mask = rng.random(arr.shape[:2]) < rate
    out = arr.copy()
    dark = rng.random(arr.shape[:2]) < 0.7
    out[mask & dark] = rng.integers(0, 60, size=3)
    out[mask & ~dark] = rng.integers(200, 256, size=3)
    return out


def degrade(
    image: Image.Image,
    profile: DegradeProfile,
    seed: int = 0,
) -> Image.Image:
    """Apply a scan-degradation profile to a rendered page."""
    if profile.name == "clean":
        return image.copy()

    rng = np.random.default_rng(seed)
    img = image.copy()

    # Skew -- scanners never feed perfectly straight. Expand + white fill so
    # rotation does not crop content away.
    if profile.skew_deg:
        angle = float(rng.uniform(-profile.skew_deg, profile.skew_deg))
        img = img.rotate(
            angle, resample=Image.BICUBIC, expand=True, fillcolor=(255, 255, 255)
        )

    if profile.brightness != 1.0:
        img = ImageEnhance.Brightness(img).enhance(profile.brightness)
    if profile.contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(profile.contrast)
    if profile.blur_radius:
        img = img.filter(ImageFilter.GaussianBlur(profile.blur_radius))

    arr = np.asarray(img).astype(np.int16)
    if profile.noise_sigma:
        arr = arr + rng.normal(0, profile.noise_sigma, arr.shape)
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    arr = _add_specks(arr, profile.speck_rate, rng)
    img = Image.fromarray(arr)

    # JPEG last -- compression artefacts sit on top of everything else, as in a
    # real scan-to-email pipeline.
    if profile.jpeg_quality < 100:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=profile.jpeg_quality)
        buf.seek(0)
        img = Image.open(buf).convert("RGB")

    return img


def degrade_pdf(
    pdf_path: Path,
    out_dir: Path,
    profiles: list[str] | None = None,
    dpi: int = 200,
    seed: int = 0,
) -> dict[str, list[Path]]:
    """Render a PDF and write one image per page per profile."""
    profiles = profiles or list(PROFILES)
    pages = pdf_to_images(pdf_path, dpi=dpi)
    stem = pdf_path.stem
    written: dict[str, list[Path]] = {}

    for pname in profiles:
        profile = PROFILES[pname]
        pdir = out_dir / pname
        pdir.mkdir(parents=True, exist_ok=True)
        paths = []
        for i, page in enumerate(pages, start=1):
            out = degrade(page, profile, seed=seed + i)
            # PNG throughout: JPEG artefacts are baked in above where the
            # profile calls for them, so the file format adds no further loss.
            p = pdir / f"{stem}_p{i}.png"
            out.save(p, format="PNG")
            paths.append(p)
        written[pname] = paths

    return written
