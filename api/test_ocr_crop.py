#!/usr/bin/env python3
"""V.5.9 wide buyer-line crop + OCR.space debug (same crop as ``parse_rafael_rfq``).

Requires ``OCR_SPACE_API_KEY``. Saves RGB crop as ``debug_crop.png``.

Usage::

    export OCR_SPACE_API_KEY=...
    python3 api/test_ocr_crop.py /path/to/RFQ.pdf
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import fitz  # PyMuPDF
import pdfplumber
from PIL import Image

_API = Path(__file__).resolve().parent
_REPO_ROOT = _API.parent
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))

from parse_rafael_rfq import (  # noqa: E402
    _BUYER_CROP_DELTA_BOTTOM,
    _BUYER_CROP_DELTA_TOP,
    _BUYER_CROP_PAD_X0_LEFT,
    _BUYER_CROP_X1_PAD_RIGHT,
    _BUYER_OCR_DPI,
    _buyer_name_from_ocr_space,
    _find_buyer_email_word,
    _page_clean_words,
)

_OUT_PATH = _REPO_ROOT / "debug_crop.png"


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python3 api/test_ocr_crop.py <path-to-rfq.pdf>", file=sys.stderr)
        return 2
    if not (os.environ.get("OCR_SPACE_API_KEY") or "").strip():
        print("Set OCR_SPACE_API_KEY in the environment.", file=sys.stderr)
        return 1
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

    ax0 = float(anchor["x0"])
    ax1 = float(anchor["x1"])
    top = float(anchor["top"])
    crop_x0 = max(0.0, ax0 - _BUYER_CROP_PAD_X0_LEFT)
    crop_x1 = ax1 + _BUYER_CROP_X1_PAD_RIGHT
    crop_top = top - _BUYER_CROP_DELTA_TOP
    crop_bottom = top - _BUYER_CROP_DELTA_BOTTOM

    rect = fitz.Rect(crop_x0, crop_top, crop_x1, crop_bottom)
    doc = fitz.open(pdf_path)
    try:
        page = doc[0]
        clip = rect & page.rect
        if clip.is_empty or clip.width <= 0 or clip.height <= 0:
            print(f"Empty clip after intersecting page: {rect!r}", file=sys.stderr)
            return 1
        zoom = _BUYER_OCR_DPI / 72.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
    finally:
        doc.close()

    img_rgb = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    img_rgb.save(_OUT_PATH.as_posix())
    print(
        f"Crop (pt): x0={crop_x0:.3f} y0={crop_top:.3f} x1={crop_x1:.3f} y1={crop_bottom:.3f}  "
        f"→ {pix.width}×{pix.height}px @ {_BUYER_OCR_DPI:.0f} DPI → {_OUT_PATH}",
    )

    clean = _buyer_name_from_ocr_space(pdf_path, anchor)
    print("CLEAN_NAME:", repr(clean))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
