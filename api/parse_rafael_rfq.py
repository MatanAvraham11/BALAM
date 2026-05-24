"""
Rafael BOM (RFQ) parser — V.5.7.

Rafael RFQ PDFs are landscape A4 with a custom subset font whose CMap is
broken for the Hebrew labels (every Hebrew glyph extracts as a
private-use codepoint at ``size = 0``). The numeric and ASCII data,
however, lives in real text spans with ``size > 0`` and stable
``x``-coordinates, so a coordinate-based pdfplumber pass recovers
everything we need:

Globals (page-header band, y ≲ 140 pt)
    * RFQ number      — sz=10, x≈133–163, y≈55      (also in ``FAX_INFO:…``)
    * Issue date      — sz=8,  x≈251–295, y≈85
    * Buyer name      — **V.5.7:** deterministic OCR only: pdfplumber finds the
      ``…@rafael.co.il`` anchor on page 1; **PyMuPDF** renders a **300 DPI** clip
      with fixed geometry above the e-mail; **Tesseract** ``heb`` reads the crop.
      There is **no** hardcoded buyer dictionary and **no** e-mail local-part
      fallback. If the anchor, Tesseract stack, or OCR output is unusable
      (fewer than two Hebrew letters), the parser emits ``""`` or ``"OCR Failed"``
      and **warnings** — never a guessed name. Set ``RAFAEL_BUYER_OCR=0`` to
      disable OCR locally (still returns ``"OCR Failed"`` with a warning).
    * Buyer email     — sz=9,  x≈100–180, y≈100     (geometry anchor for OCR crop)
    * Buyer phone     — sz=9,  x≈130–180, y≈88
    * Submission date — first ``dd/mm/yyyy`` found in ``extract_text()`` in page order
      (cover-letter paragraph; many RFQs omit it from the text layer — then issue date)

Locals (per delivery row, repeating per part block)
    * Quantity         — sz=9, x≈266–290     (``\\d+\\.\\d{2}``)
    * Weeks ARO        — sz=8, x≈358–372     (integer, ``זמן אספקה בשבועות`` column in PDF)
    * Delivery seq #   — sz=9, x≈400–405     (1..N within part)
    * ``N`` flag       — sz=9, x≈479–486     (not exported)
    * ``Each`` unit    — sz=9, x≈503–521
    * Description      — sz=9, x≥527
    * Rafael part #    — sz=8, x≈731–779     (alphanumeric all-caps)
    * Part seq index   — sz=9, x≈795–800
    * FAI marker       — sz=8, x≈30–48, ``FAI−`` then a digit just below

Export TXT: eight tab-separated columns, ``\u05de\u05e1\u05e4\u05e8 \u05e9\u05d5\u05e8\u05d4`` first,
then globals + locals (``\u05d6\u05de\u05df \u05d0\u05e1\u05e4\u05e7\u05d4 \u05d1\u05e9\u05d1\u05d5\u05e2\u05d5\u05ea`` = integer weeks, not a calendar date).
"""

from __future__ import annotations

import os
import re
import shutil
import warnings
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
import pdfplumber
from PIL import Image
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

FAI_NOT_REQUIRED = "לא נדרש"


class Delivery(BaseModel):
    quantity: float = Field(description="כמות נדרשת")
    weeks_aro: int = Field(
        description="זמן אספקה בשבועות — מספר שלם מעמודת ARO ב-PDF",
    )
    fai: str = Field(
        default=FAI_NOT_REQUIRED,
        description='"FAI 1" / "FAI 2" / "FAI 3" / "לא נדרש"',
    )


class PartBlock(BaseModel):
    rafael_pn: str = Field(description="מקט רפאל")
    deliveries: list[Delivery] = Field(default_factory=list)


class RafaelRfq(BaseModel):
    rfq_number: str = Field(description='מספר בלם')
    buyer_name: str = Field(description="שם קניין")
    submission_date: str = Field(description="תאריך סופי להגשה (dd/mm/yyyy)")
    parts: list[PartBlock] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Coordinate-band constants (calibrated against the three reference RFQs)
# ---------------------------------------------------------------------------

# Page-header band (globals)
_RFQ_X = (128.0, 168.0)
_RFQ_Y = (50.0, 62.0)
_ISSUE_DATE_X = (245.0, 305.0)
_ISSUE_DATE_Y = (80.0, 90.0)
_EMAIL_X_MAX = 200.0
_EMAIL_Y = (86.0, 112.0)

# V.5.7 buyer-name OCR crop (PDF user space, pt): tight band above e-mail anchor.
_BUYER_CROP_ANCHOR_DELTA_TOP = 45.0
_BUYER_CROP_ANCHOR_DELTA_BOTTOM = 5.0
_BUYER_CROP_PAD_X0 = 10.0
_BUYER_CROP_PAD_X1 = 100.0
_BUYER_OCR_DPI = 300.0

# Per-row column x-bands
_QTY_X = (255.0, 295.0)
_OFFSET_X = (355.0, 380.0)
_SEQ_X = (395.0, 410.0)
_EACH_X = (495.0, 525.0)
_PARTNUM_X = (725.0, 785.0)
_FAI_FLAG_X = (28.0, 50.0)
_FAI_DIGIT_X = (32.0, 45.0)

# Vertical tolerance when grouping items into the same row band
_ROW_Y_TOL = 4.0
# FAI marker (``FAI−``) sits ~9 pt above its accompanying digit. We accept a
# digit whose y is in (marker.top, marker.top + _FAI_DIGIT_DY_MAX).
_FAI_DIGIT_DY_MAX = 15.0

# Words above this y are inside the page-header band and never table data
_HEADER_Y_MAX = 140.0

# Submission-date pattern (dd/mm/yyyy)
_RE_SUB_DATE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
# Issue-date pattern (dd-MMM-yy with either ASCII '-' or Unicode '−')
_RE_ISSUE_DATE = re.compile(r"^(\d{2})[−\-]([A-Z]{3})[−\-](\d{2})$")
# Rafael part-number heuristic — uppercase alnum, has at least one digit
_RE_PARTNUM = re.compile(r"^(?=.*\d)[A-Z][A-Z0-9]{4,12}$")
# Quantity / integer / decimal helpers
_RE_QTY = re.compile(r"^\d+\.\d{1,3}$")
_RE_INT = re.compile(r"^\d+$")

_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

# Keep only words whose text is printable ASCII + Unicode minus
_ASCII_OK = re.compile(r"^[\u0020-\u007E\u2212]+$")


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def _page_clean_words(page: Any) -> list[dict[str, Any]]:
    """Return only the real-text words (size > 0, printable ASCII)."""
    raw = page.extract_words(
        use_text_flow=False,
        keep_blank_chars=False,
        extra_attrs=["size", "fontname"],
    )
    out: list[dict[str, Any]] = []
    for w in raw:
        if (w.get("size") or 0) <= 0:
            continue
        text = w.get("text") or ""
        if not _ASCII_OK.match(text):
            continue
        out.append({
            "text": text,
            "x0": float(w["x0"]),
            "x1": float(w["x1"]),
            "top": float(w["top"]),
            "size": float(w["size"]),
        })
    return out


def _in_x(word: dict[str, Any], lo: float, hi: float) -> bool:
    cx = (word["x0"] + word["x1"]) / 2
    return lo <= cx <= hi


def _y_close(a: float, b: float, tol: float = _ROW_Y_TOL) -> bool:
    return abs(a - b) <= tol


def _format_issue_date(token: str) -> str:
    """``04-MAY-26`` / ``04−MAY−26`` → ``04/05/2026``."""
    m = _RE_ISSUE_DATE.match(token)
    if not m:
        return ""
    day, mon, yy = m.groups()
    month = _MONTHS.get(mon.upper())
    if not month:
        return ""
    year = 2000 + int(yy)
    return f"{int(day):02d}/{month:02d}/{year:04d}"


def _parse_dmy(token: str) -> date | None:
    if not token or not _RE_SUB_DATE.match(token):
        return None
    try:
        return datetime.strptime(token, "%d/%m/%Y").date()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# V.5.7 — Buyer name: PyMuPDF geometric crop + Tesseract Hebrew (OCR-only)
# ---------------------------------------------------------------------------


def _hebrew_letter_count(s: str) -> int:
    return sum(1 for c in s if "\u0590" <= c <= "\u05FF")


@lru_cache(maxsize=1)
def _tesseract_hebrew_ready() -> bool:
    """True when ``tesseract`` is on PATH, ``pytesseract`` importable, and ``heb`` exists."""
    if os.environ.get("RAFAEL_BUYER_OCR", "").strip().lower() in (
        "0", "false", "no", "off",
    ):
        return False
    if not shutil.which("tesseract"):
        return False
    try:
        import pytesseract as pt  # noqa: PLC0415

        langs = pt.get_languages(config="")
    except Exception:
        return False
    return "heb" in langs


def _find_buyer_email_word(
    words: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """First ``…@rafael.co.il`` token on page 1 (header geometry); pdfplumber anchor."""
    strict = [
        w for w in words
        if _in_x(w, 0.0, _EMAIL_X_MAX)
        and _EMAIL_Y[0] <= w["top"] <= _EMAIL_Y[1]
        and (w.get("text") or "").lower().endswith("@rafael.co.il")
    ]
    pool = strict if strict else [
        w for w in words
        if _in_x(w, 0.0, _EMAIL_X_MAX)
        and 55.0 <= w["top"] <= _HEADER_Y_MAX
        and (w.get("text") or "").lower().endswith("@rafael.co.il")
    ]
    if not pool:
        return None
    centre = (_EMAIL_Y[0] + _EMAIL_Y[1]) / 2.0
    return min(pool, key=lambda w: abs(float(w["top"]) - centre))


def _strip_kinyan_noise(line: str) -> str:
    s = re.sub(
        r"^[:\s\u05f3\u05f4]*קניין[:\s\u05f3\u05f4]*",
        "",
        line.strip(),
    )
    s = re.sub(
        r"^[:\s\u05f3\u05f4]*קנין[:\s\u05f3\u05f4]*",
        "",
        s,
    )
    return s.lstrip(": \u05f3\u05f4").strip()


def _hebrew_only_spaced(s: str) -> str:
    kept: list[str] = []
    for ch in s:
        if "\u0590" <= ch <= "\u05FF":
            kept.append(ch)
        elif ch.isspace():
            kept.append(" ")
    return re.sub(r"\s+", " ", "".join(kept)).strip()


def _best_hebrew_line_orientation(line: str) -> str:
    """Pick forward vs reversed string by Hebrew letter count (Tesseract RTL quirks)."""
    line = line.strip()
    if not line:
        return ""
    a = _hebrew_only_spaced(_strip_kinyan_noise(line))
    b = _hebrew_only_spaced(_strip_kinyan_noise(line[::-1]))
    if _hebrew_letter_count(b) > _hebrew_letter_count(a):
        return b
    return a


def _clean_ocr_buyer_output(raw: str) -> str:
    """Strip noise; prefer the line with the most Hebrew letters."""
    if not raw or not raw.strip():
        return ""
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return ""
    best = ""
    best_score = (-1, -1)
    for ln in lines:
        oriented = _best_hebrew_line_orientation(ln)
        if _hebrew_letter_count(oriented) < 2:
            continue
        key = (_hebrew_letter_count(oriented), len(oriented))
        if key > best_score:
            best_score = key
            best = oriented
    return best


def _buyer_name_from_ocr_pymupdf_tesseract(
    pdf_path: Path,
    email_w: dict[str, Any],
) -> str:
    """V.5.7 fixed crop above e-mail → 300 DPI pixmap (fitz) → Tesseract ``heb``."""
    import pytesseract  # noqa: PLC0415

    x0 = float(email_w["x0"])
    x1 = float(email_w["x1"])
    etop = float(email_w["top"])
    clip_x0 = max(0.0, x0 - _BUYER_CROP_PAD_X0)
    clip_x1 = x1 + _BUYER_CROP_PAD_X1
    clip_y0 = etop - _BUYER_CROP_ANCHOR_DELTA_TOP
    clip_y1 = etop - _BUYER_CROP_ANCHOR_DELTA_BOTTOM

    rect = fitz.Rect(clip_x0, clip_y0, clip_x1, clip_y1)
    if rect.is_empty or rect.width <= 0 or rect.height <= 0:
        return ""

    doc = fitz.open(pdf_path)
    try:
        page = doc[0]
        clip = rect & page.rect
        if clip.is_empty:
            return ""
        zoom = _BUYER_OCR_DPI / 72.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
    finally:
        doc.close()

    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    try:
        raw = pytesseract.image_to_string(
            img,
            lang="heb",
            config="--psm 6 -c preserve_interword_spaces=1",
        )
    except Exception:
        return ""
    return _clean_ocr_buyer_output(raw)


def _detect_buyer(pdf_path: Path, pages: list[list[dict[str, Any]]]) -> str:
    """Buyer Hebrew name: OCR path only; no e-mail dictionary or local-part fallback."""
    if not pages:
        warnings.warn(
            "Rafael buyer: PDF has no pages (cannot run buyer OCR).",
            UserWarning,
            stacklevel=2,
        )
        return "OCR Failed"
    email_w = _find_buyer_email_word(pages[0])
    if email_w is None:
        warnings.warn(
            "Rafael buyer: no word ending with @rafael.co.il on page 1 (cannot build OCR crop).",
            UserWarning,
            stacklevel=2,
        )
        return ""
    if not _tesseract_hebrew_ready():
        warnings.warn(
            "Rafael buyer OCR unavailable: need tesseract on PATH, Hebrew traineddata "
            "(heb), and pytesseract. Set RAFAEL_BUYER_OCR=0 only to disable OCR locally.",
            UserWarning,
            stacklevel=2,
        )
        return "OCR Failed"
    name = _buyer_name_from_ocr_pymupdf_tesseract(pdf_path, email_w)
    if _hebrew_letter_count(name) >= 2:
        return name
    warnings.warn(
        f"Rafael buyer OCR: insufficient Hebrew in OCR output ({name!r}).",
        UserWarning,
        stacklevel=2,
    )
    return "OCR Failed"


# ---------------------------------------------------------------------------
# Globals detection
# ---------------------------------------------------------------------------

def _detect_rfq_number(pages: list[list[dict[str, Any]]]) -> str:
    """Find the 6-digit RFQ number in the page-header band.

    Prefers the standalone ``684XXX`` token at (x≈133–163, y≈55). Falls back
    to ``FAX_INFO:<rfq>:`` capture if the dedicated token is missing.
    """
    for words in pages:
        for w in words:
            if not (_in_x(w, *_RFQ_X) and _RFQ_Y[0] <= w["top"] <= _RFQ_Y[1]):
                continue
            if re.fullmatch(r"\d{6}", w["text"]):
                return w["text"]
    for words in pages:
        for w in words:
            m = re.match(r"FAX_INFO:(\d+):", w["text"])
            if m:
                return m.group(1)
    return ""


def _detect_issue_date(pages: list[list[dict[str, Any]]]) -> str:
    for words in pages:
        for w in words:
            if not (_in_x(w, *_ISSUE_DATE_X)
                    and _ISSUE_DATE_Y[0] <= w["top"] <= _ISSUE_DATE_Y[1]):
                continue
            formatted = _format_issue_date(w["text"])
            if formatted:
                return formatted
    return ""


def _detect_submission_date(
    pdf_pages_raw: list[str],
    issue_date_str: str,
) -> str:
    """First ``dd/mm/yyyy`` in ``extract_text()`` in ascending page order.

    This matches the cover / supplier-letter region when the date is present
    in the text layer. If the PDF only embeds the deadline as artwork, we
    fall back to the issue-date string (still a valid ``dd/mm/yyyy``).
    """
    date_re = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")
    for text in pdf_pages_raw:
        m = date_re.search(text or "")
        if m:
            token = m.group(1)
            if _parse_dmy(token):
                return token
    return issue_date_str


# ---------------------------------------------------------------------------
# Part-block detection
# ---------------------------------------------------------------------------

def _classify_fai_digit(digit: str | None) -> str:
    if digit in {"1", "2", "3"}:
        return f"FAI {digit}"
    return FAI_NOT_REQUIRED


def _find_fai_for_row(
    words: list[dict[str, Any]],
    row_y: float,
) -> str:
    """A delivery row gets a FAI level when a ``FAI−`` marker sits at
    roughly the same y *and* a digit appears in the FAI band just below.

    Anything else (no marker, no digit, or a non-1/2/3 digit) ⇒ ``לא נדרש``
    so the column is never empty.
    """
    marker = None
    for w in words:
        if not _in_x(w, *_FAI_FLAG_X):
            continue
        if w["text"].startswith("FAI") and _y_close(w["top"], row_y):
            marker = w
            break
    if marker is None:
        return FAI_NOT_REQUIRED
    digit_word = next(
        (
            w for w in words
            if _in_x(w, *_FAI_DIGIT_X)
            and marker["top"] < w["top"] <= marker["top"] + _FAI_DIGIT_DY_MAX
            and _RE_INT.match(w["text"])
        ),
        None,
    )
    return _classify_fai_digit(digit_word["text"] if digit_word else None)


def _detect_part_blocks(
    pages: list[list[dict[str, Any]]],
) -> list[PartBlock]:
    blocks: list[PartBlock] = []

    for words in pages:
        # A real part header row always has the unit label ``Each`` in the
        # unit column at the same y. This filters out the page footer's
        # ``PRODA - <USER> - XPOTDP01 - <id>`` line whose ``XPOTDP01`` token
        # otherwise lands inside _PARTNUM_X.
        each_ys = [
            w["top"] for w in words
            if _in_x(w, *_EACH_X) and w["text"] == "Each"
        ]
        part_words = [
            w for w in words
            if _in_x(w, *_PARTNUM_X)
            and w["top"] > _HEADER_Y_MAX
            and _RE_PARTNUM.match(w["text"])
            and any(_y_close(w["top"], ey) for ey in each_ys)
        ]
        part_words.sort(key=lambda w: w["top"])
        if not part_words:
            continue

        # Each part header row defines a vertical interval up to the next part.
        part_ys = [w["top"] for w in part_words] + [10_000.0]
        for idx, part_word in enumerate(part_words):
            top = part_word["top"] - _ROW_Y_TOL
            bottom = part_ys[idx + 1] - _ROW_Y_TOL
            qty_rows = sorted(
                [
                    w for w in words
                    if _in_x(w, *_QTY_X)
                    and top <= w["top"] <= bottom
                    and _RE_QTY.match(w["text"])
                ],
                key=lambda w: w["top"],
            )
            block = PartBlock(rafael_pn=part_word["text"], deliveries=[])
            for q in qty_rows:
                quantity = float(q["text"])

                # Day-offset on the same row band
                offset_word = next(
                    (
                        w for w in words
                        if _in_x(w, *_OFFSET_X)
                        and _y_close(w["top"], q["top"])
                        and _RE_INT.match(w["text"])
                    ),
                    None,
                )
                weeks_aro = int(offset_word["text"]) if offset_word else 0

                fai = _find_fai_for_row(words, q["top"])
                block.deliveries.append(
                    Delivery(
                        quantity=quantity,
                        weeks_aro=weeks_aro,
                        fai=fai,
                    )
                )
            blocks.append(block)

    return blocks


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_rafael_rfq(pdf_path: str | Path) -> RafaelRfq:
    """Parse a Rafael RFQ PDF and return globals + per-part delivery list."""
    pdf_path = Path(pdf_path)
    with pdfplumber.open(str(pdf_path)) as pdf:
        pages = [_page_clean_words(p) for p in pdf.pages]
        extract_text_pages = [(p.extract_text() or "") for p in pdf.pages]

    rfq_number = _detect_rfq_number(pages)
    issue_date = _detect_issue_date(pages)
    buyer_name = _detect_buyer(pdf_path, pages)
    submission_date = _detect_submission_date(extract_text_pages, issue_date)

    parts = _detect_part_blocks(pages)

    return RafaelRfq(
        rfq_number=rfq_number,
        buyer_name=buyer_name,
        submission_date=submission_date,
        parts=parts,
    )


# ---------------------------------------------------------------------------
# Row flattening + TSV writer (V.5.7 spec)
# ---------------------------------------------------------------------------

RAFAEL_TXT_COLUMNS: list[str] = [
    "מספר שורה",
    "מספר בלם",
    "שם קניין",
    "תאריך סופי להגשה",
    "מקט רפאל",
    "כמות נדרשת",
    "זמן אספקה בשבועות",
    "FAI",
]


def flatten_rafael_to_rows(rfq: RafaelRfq) -> list[dict[str, Any]]:
    """Flatten parts × deliveries into the 8-column row schema.

    Row numbers are globally sequential 1..N across the whole RFQ
    (not per-part). ``מספר שורה`` is the first column (sequential index).
    """
    rows: list[dict[str, Any]] = []
    line_no = 0
    for part in rfq.parts:
        for d in part.deliveries:
            line_no += 1
            rows.append({
                "מספר שורה": line_no,
                "מספר בלם": rfq.rfq_number,
                "שם קניין": rfq.buyer_name,
                "תאריך סופי להגשה": rfq.submission_date,
                "מקט רפאל": part.rafael_pn,
                "כמות נדרשת": d.quantity,
                "זמן אספקה בשבועות": d.weeks_aro,
                "FAI": d.fai,
            })
    return rows


def format_rafael_tsv_body(rows: list[dict[str, Any]]) -> str:
    """Build a strict TSV body: tab between fields, CRLF line endings.

    No CSV-style quoting / escaping (matches the Balam TSV contract so
    Excel on a Hebrew Windows / Mac opens the result cleanly under the
    windows-1255 encoding the API uses).
    """
    lines: list[str] = ["\t".join(RAFAEL_TXT_COLUMNS)]
    for r in rows:
        lines.append("\t".join(str(r.get(col, "")) for col in RAFAEL_TXT_COLUMNS))
    return "\r\n".join(lines) + "\r\n"


# ---------------------------------------------------------------------------
# CLI test harness — `python parse_rafael_rfq.py <rfq.pdf> [<rfq.pdf> ...]` (V.5.7)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python parse_rafael_rfq.py <rfq.pdf> [<rfq.pdf> ...]")
        sys.exit(1)

    for arg in sys.argv[1:]:
        pdf = Path(arg)
        if not pdf.exists():
            print(f"File not found: {pdf}")
            continue
        rfq = parse_rafael_rfq(pdf)
        rows = flatten_rafael_to_rows(rfq)
        body = format_rafael_tsv_body(rows)
        out_path = pdf.with_name(pdf.stem + ".rafael.txt")
        out_path.write_text(body, encoding="utf-8")
        print(
            f"{pdf.name}: rfq={rfq.rfq_number} buyer={rfq.buyer_name} "
            f"sub={rfq.submission_date} parts={len(rfq.parts)} rows={len(rows)} "
            f"-> {out_path.name}"
        )
