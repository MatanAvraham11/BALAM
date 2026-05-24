#!/usr/bin/env python3
"""V.5.7 visual crop probe: save the buyer-name region above the Rafael e-mail anchor.

Uses pdfplumber on page 1 to locate a word ending with ``@rafael.co.il``, applies the
fixed V.5.7 crop geometry in PDF user space, renders that rectangle at 300 DPI with
PyMuPDF (fitz), and writes ``debug_crop.png`` at the repository root. Does not run
Tesseract.

Usage::

    python3 api/test_ocr_crop.py /path/to/RFQ.pdf
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz  # PyMuPDF
import pdfplumber

_API = Path(__file__).resolve().parent
_REPO_ROOT = _API.parent
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))

from parse_rafael_rfq import (  # noqa: E402
    _find_buyer_email_word,
    _page_clean_words,
)

_OUT_PATH = _REPO_ROOT / "debug_crop.png"

# V.5.7 geometry (must match ``parse_rafael_rfq._buyer_name_from_ocr_pymupdf_tesseract``).
_CROP_TOP_DELTA = 45.0
_CROP_BOTTOM_DELTA = 5.0
_CROP_X0_PAD = 10.0
_CROP_X1_PAD = 100.0
_RENDER_DPI = 300.0


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python3 api/test_ocr_crop.py <path-to-rfq.pdf>", file=sys.stderr)
        return 2
    pdf_path = Path(sys.argv[1]).expanduser().resolve()
    if not pdf_path.is_file():
        print(f"Not a file: {pdf_path}", file=sys.stderr)
        return 1

    with pdfplumber.open(str(pdf_path)) as pdf:
        if not pdf.pages:
            print("PDF has no pages.", file=sys.stderr)
            return 1
        words = _page_clean_words(pdf.pages[0])

    anchor = _find_buyer_email_word(words)
    if anchor is None:
        print(
            "No anchor word ending with @rafael.co.il found on page 1.",
            file=sys.stderr,
        )
        return 1

    x0 = float(anchor["x0"])
    x1 = float(anchor["x1"])
    top = float(anchor["top"])
    crop_x0 = max(0.0, x0 - _CROP_X0_PAD)
    crop_x1 = x1 + _CROP_X1_PAD
    crop_top = top - _CROP_TOP_DELTA
    crop_bottom = top - _CROP_BOTTOM_DELTA

    rect = fitz.Rect(crop_x0, crop_top, crop_x1, crop_bottom)
    doc = fitz.open(pdf_path)
    try:
        page = doc[0]
        clip = rect & page.rect
        if clip.is_empty or clip.width <= 0 or clip.height <= 0:
            print(f"Empty clip after intersecting page: {rect!r}", file=sys.stderr)
            return 1
        zoom = _RENDER_DPI / 72.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
    finally:
        doc.close()

    pix.save(_OUT_PATH.as_posix())
    print(
        f"Anchor {anchor.get('text')!r} @ x0={x0:.1f} x1={x1:.1f} top={top:.1f}\n"
        f"Crop rect PDF pt: ({crop_x0:.1f}, {crop_top:.1f}) – ({crop_x1:.1f}, {crop_bottom:.1f})\n"
        f"Pixmap: {pix.width}×{pix.height} px @ {_RENDER_DPI:.0f} DPI\n"
        f"Wrote {_OUT_PATH}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
