#!/usr/bin/env python3
"""V.6.0 debug: buyer-name crop + submission-deadline line crop (same geometry as parser).

Requires ``OCR_SPACE_API_KEY``. Writes:

* ``debug_crop.png`` — buyer-name surgical crop (same as ``parse_rafael_rfq``).
* ``debug_date_crop.png`` — cover-letter deadline line crop for ``submission_date``.

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
    _submission_due_date_from_ocr_space,
    _submission_due_surgical_rect_from_email,
)

_BUYER_OUT = _REPO_ROOT / "debug_crop.png"
_DATE_OUT = _REPO_ROOT / "debug_date_crop.png"


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
            print(f"Empty buyer clip after intersecting page: {rect!r}", file=sys.stderr)
            return 1
        zoom = _BUYER_OCR_DPI / 72.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
    finally:
        doc.close()

    img_rgb = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    img_rgb.save(_BUYER_OUT.as_posix())
    print(
        f"Buyer crop (pt): x0={crop_x0:.3f} y0={crop_top:.3f} x1={crop_x1:.3f} y1={crop_bottom:.3f}  "
        f"→ {pix.width}×{pix.height}px @ {_BUYER_OCR_DPI:.0f} DPI → {_BUYER_OUT}",
    )

    clean, _reason = _buyer_name_from_ocr_space(pdf_path, anchor)
    print("CLEAN_NAME:", repr(clean))

    # Submission deadline line (V.6.0)
    drect = _submission_due_surgical_rect_from_email(anchor)
    doc2 = fitz.open(pdf_path)
    try:
        page2 = doc2[0]
        dclip = drect & page2.rect
        if dclip.is_empty or dclip.width <= 0 or dclip.height <= 0:
            print(f"Empty date clip: {drect!r}", file=sys.stderr)
            return 1
        mat2 = fitz.Matrix(zoom, zoom)
        pix2 = page2.get_pixmap(matrix=mat2, clip=dclip, alpha=False)
    finally:
        doc2.close()

    img_date = Image.frombytes("RGB", (pix2.width, pix2.height), pix2.samples)
    img_date.save(_DATE_OUT.as_posix())
    print(
        f"Date crop (pt): x0={drect.x0:.3f} y0={drect.y0:.3f} x1={drect.x1:.3f} y1={drect.y1:.3f}  "
        f"→ {pix2.width}×{pix2.height}px → {_DATE_OUT}",
    )
    due = _submission_due_date_from_ocr_space(pdf_path, anchor)
    print("SUBMISSION_DUE_OCR:", repr(due))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
