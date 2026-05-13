"""
Rafael RFQ — OCR helpers for globals (V.5.2).

The Rafael subset fonts do not expose Hebrew or the cover-letter deadline as
real Unicode in ``extract_text()`` / ``extract_words``. We render tight
regions of **page 1** with PyMuPDF and run **Tesseract** (``heb+eng``) to read:

* **שם קניין** — line containing ``קניין:`` + Hebrew name.
* **תאריך סופי להגשה** — date after ``לא יאוחר מיום`` inside the supplier letter.

Deployment
~~~~~~~~~~

* Requires the **tesseract** binary on ``PATH`` and Hebrew traineddata
  (``heb``). macOS: ``brew install tesseract tesseract-lang``.
* **Vercel** serverless images do **not** include Tesseract by default; either
  add a custom build layer that installs ``tesseract-ocr`` + ``tesseract-ocr-heb``,
  run the API on a host/Docker image with Tesseract, or rely on the parser
  fallback (e-mail map + first text-layer date / issue date).

Environment
~~~~~~~~~~~

* ``RAFAEL_OCR`` — ``1`` (default) try OCR when ``tesseract`` exists; ``0`` /
  ``false`` / ``no`` disables OCR entirely (always use the V.5.1 text fallback).
"""

from __future__ import annotations

import io
import os
import re
import shutil
from pathlib import Path

import fitz  # PyMuPDF

# Optional: import fails only if someone imports this module without Pillow
from PIL import Image, ImageOps

# ---------------------------------------------------------------------------
# Page-1 ROI rectangles in **normalised** PDF coordinates (0–1 of mediabox).
# Calibrated on landscape Rafael RFQs (≈842×595): left header block + letter.
# ---------------------------------------------------------------------------

_BUYER_ROI_NORM = (0.04, 0.11, 0.56, 0.24)  # x0, y0, x1, y1
_LETTER_ROI_NORM = (0.26, 0.16, 0.98, 0.40)

_RENDER_ZOOM = 3.0  # scales pixmap for OCR (~216 dpi on vector pages)

_RE_SUB_DATE_STRICT = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_RE_DEADLINE_ANCHOR = re.compile(
    r"לא\s*(?:י\s*אוחר|יאוחר)\s*מיום\s*"
    r"(\d{1,2}\s*[/\u2212.\-|]\s*\d{1,2}\s*[/\u2212.\-|]\s*\d{4})",
    re.UNICODE,
)
_RE_DEADLINE_LOOSE = re.compile(
    r"לא[^\d]{0,48}?מיום[^\d]{0,8}?(\d{1,2}\s*[/\u2212.\-|]\s*\d{1,2}\s*[/\u2212.\-|]\s*\d{4})",
    re.UNICODE | re.DOTALL,
)
# No ``\\b``: Hebrew letters are "word" chars — dates can touch עברית without a boundary.
_RE_ANY_DMY = re.compile(
    r"(?<!\d)(\d{1,2}\s*[/\u2212.\-|]\s*\d{1,2}\s*[/\u2212.\-|]\s*\d{4})(?!\d)",
)
_RE_BUYER_LINE = re.compile(
    r"קניין\s*[:׳]?\s*([\u0590-\u05FF][\u0590-\u05FF\s\.'״\-]{0,80})",
    re.UNICODE,
)


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def ocr_globally_enabled() -> bool:
    v = (os.environ.get("RAFAEL_OCR") or "1").strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    return tesseract_available()


def _tesseract_lang_arg() -> str:
    try:
        import pytesseract  # type: ignore[import-untyped]

        langs = pytesseract.get_languages()
        if "heb" in langs:
            return "heb+eng"
    except Exception:
        pass
    return "eng"


def _run_tesseract(img: Image.Image, psm: int) -> str:
    import pytesseract  # type: ignore[import-untyped]

    lang = _tesseract_lang_arg()
    cfg = f"--psm {psm} -c preserve_interword_spaces=1"
    return pytesseract.image_to_string(img, lang=lang, config=cfg) or ""


def _pixmap_to_pil(page: fitz.Page, rect: fitz.Rect, zoom: float) -> Image.Image:
    mat = fitz.Matrix(zoom, zoom)
    # clip in PDF space; matrix scales the whole page then clips internally
    pix = page.get_pixmap(matrix=mat, clip=rect, alpha=False)
    return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")


def _prep_for_ocr(img: Image.Image) -> Image.Image:
    gray = ImageOps.grayscale(img)
    return ImageOps.autocontrast(gray, cutoff=1)


def _norm_rect(page: fitz.Page, norm: tuple[float, float, float, float]) -> fitz.Rect:
    r = page.rect
    x0, y0, x1, y1 = norm
    return fitz.Rect(
        r.x0 + x0 * r.width,
        r.y0 + y0 * r.height,
        r.x0 + x1 * r.width,
        r.y0 + y1 * r.height,
    )


def normalize_dmy_token(raw: str) -> str:
    """``8 / 05 / 2026`` or ``8-05-2026`` → ``08/05/2026``."""
    s = raw.replace("\u2212", "/").replace("-", "/").replace("|", "/").replace(".", "/")
    s = re.sub(r"\s+", "", s)
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if not m:
        return ""
    d, mo, y = m.groups()
    try:
        dd = int(d)
        mm = int(mo)
        yy = int(y)
    except ValueError:
        return ""
    if not (1 <= dd <= 31 and 1 <= mm <= 12 and 2000 <= yy <= 2100):
        return ""
    return f"{dd:02d}/{mm:02d}/{yy:04d}"


def parse_buyer_from_ocr_text(text: str) -> str:
    """Parse Hebrew buyer name from OCR output of the header ROI."""
    if not text or not text.strip():
        return ""
    t = text.replace("\u200f", "").replace("\u200e", "")
    m = _RE_BUYER_LINE.search(t)
    if not m:
        # OCR sometimes drops yod in קניין
        m = re.search(
            r"קנין\s*[:׳]?\s*([\u0590-\u05FF][\u0590-\u05FF\s\.'״\-]{0,80})",
            t,
            re.UNICODE,
        )
        if not m:
            return ""
    name = m.group(1).strip()
    name = re.sub(r"\s+", " ", name)
    # Stop at obvious noise (Latin email start)
    if "@" in name:
        name = name.split("@", 1)[0].strip()
    return name.strip(" -:\t")[:120]


def parse_submission_deadline_from_ocr_text(text: str) -> str:
    """Parse ``dd/mm/yyyy`` deadline from OCR of the supplier-letter ROI."""
    if not text or not text.strip():
        return ""
    t = text.replace("\u200f", "").replace("\u200e", "")

    for pat in (_RE_DEADLINE_ANCHOR, _RE_DEADLINE_LOOSE):
        m = pat.search(t)
        if m:
            norm = normalize_dmy_token(m.group(1))
            if norm and _RE_SUB_DATE_STRICT.match(norm):
                return norm

    # Last resort: first plausible date **only within this ROI text**
    m2 = _RE_ANY_DMY.search(t)
    if m2:
        norm = normalize_dmy_token(m2.group(1))
        if norm and _RE_SUB_DATE_STRICT.match(norm):
            return norm
    return ""


def try_extract_globals_via_ocr(pdf_path: str | Path) -> tuple[str, str]:
    """Return ``(buyer_name, submission_date)`` from page-1 OCR, or ``("", "")``.

    On any failure (missing tess, bad PDF, OCR error) returns empty strings so
    the caller can fall back to text-based heuristics.
    """
    if not ocr_globally_enabled():
        return "", ""

    pdf_path = Path(pdf_path)
    buyer_txt = ""
    letter_txt = ""
    doc: fitz.Document | None = None
    try:
        doc = fitz.open(pdf_path)
        page = doc.load_page(0)
        br = _norm_rect(page, _BUYER_ROI_NORM)
        lr = _norm_rect(page, _LETTER_ROI_NORM)

        img_b = _prep_for_ocr(_pixmap_to_pil(page, br, _RENDER_ZOOM))
        img_l = _prep_for_ocr(_pixmap_to_pil(page, lr, _RENDER_ZOOM))

        buyer_txt = _run_tesseract(img_b, psm=7)
        letter_txt = _run_tesseract(img_l, psm=6)
    except Exception:
        return "", ""
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass

    buyer = parse_buyer_from_ocr_text(buyer_txt)
    sub = parse_submission_deadline_from_ocr_text(letter_txt)
    return buyer, sub
