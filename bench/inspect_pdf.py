"""Quick triage for a candidate source PDF.

Tells us the three things that decide whether a document is usable as test data:
how long it is, whether it is born-digital or scanned (text layer present?), and
what the content actually looks like.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pypdfium2 as pdfium


def triage(path: Path, sample_pages: int = 6, chars: int = 700) -> None:
    doc = pdfium.PdfDocument(str(path))
    n = len(doc)
    print(f"\n{'=' * 72}\n{path.name}\n{'=' * 72}")
    print(f"pages: {n}   size: {path.stat().st_size / 1024 / 1024:.2f} MB")

    # Text-layer coverage across a spread of pages tells us scanned vs digital.
    step = max(1, n // 25)
    probe = list(range(0, n, step))[:25]
    lengths = []
    for i in probe:
        try:
            lengths.append(len(doc[i].get_textpage().get_text_range().strip()))
        except Exception:
            lengths.append(0)

    empty = sum(1 for x in lengths if x < 50)
    avg = sum(lengths) / len(lengths) if lengths else 0
    print(f"text layer: avg {avg:.0f} chars/page over {len(probe)} sampled pages")
    print(f"            {empty}/{len(probe)} sampled pages have <50 chars "
          f"({'SCANNED / image-only' if empty > len(probe) * 0.6 else 'BORN-DIGITAL (has text layer)'})")

    for i in list(range(min(sample_pages, n))):
        try:
            txt = doc[i].get_textpage().get_text_range().strip()
        except Exception as e:
            txt = f"<error: {e}>"
        txt = " ".join(txt.split())
        print(f"\n--- page {i + 1} ---\n{txt[:chars]}")

    doc.close()


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        triage(Path(arg))
