#!/usr/bin/env python3
"""V.5.7 wide buyer-line crop + OCR debug (bulletproof band above e-mail).

Wide box: ``anchor_x0−20 … anchor_x1+150``, ``anchor_top−45 … anchor_top−15`` at **300 DPI**,
saved as ``debug_crop.png`` (RGB). Tesseract ``heb`` ``--psm 7`` runs on a **grayscale**
copy of the crop (same as ``parse_rafael_rfq``); strict Python
cleaning removes ``קניין``, colons, ASCII hyphens, and newlines.

Usage::

    python3 api/test_ocr_crop.py /path/to/RFQ.pdf
"""

from __future__ import annotations

import shutil
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
    _find_buyer_email_word,
    _page_clean_words,
)

_OUT_PATH = _REPO_ROOT / "debug_crop.png"


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
    img = img_rgb.convert("L")

    print(
        f"Crop (pt): x0={crop_x0:.3f} y0={crop_top:.3f} x1={crop_x1:.3f} y1={crop_bottom:.3f}  "
        f"→ {pix.width}×{pix.height}px @ {_BUYER_OCR_DPI:.0f} DPI → {_OUT_PATH}",
    )

    if not shutil.which("tesseract"):
        print("SKIP OCR: tesseract not on PATH", file=sys.stderr)
        return 0
    try:
        import pytesseract  # noqa: PLC0415
    except ModuleNotFoundError:
        print("SKIP OCR: pytesseract not installed", file=sys.stderr)
        return 0
    if "heb" not in pytesseract.get_languages(config=""):
        print("SKIP OCR: tesseract lacks heb", file=sys.stderr)
        return 0

    raw_ocr = pytesseract.image_to_string(
        img,
        lang="heb",
        config="--psm 7",
    )
    clean_name = (
        raw_ocr.replace("קניין", "")
        .replace(":", "")
        .replace("-", "")
        .replace("\n", "")
        .strip()
    )

    print(f"RAW OCR: {repr(raw_ocr)}")
    print(f"CLEAN NAME: '{clean_name}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
