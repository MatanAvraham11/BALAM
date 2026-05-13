"""
Rafael BOM (RFQ) parser — V.5.1.

Rafael RFQ PDFs are landscape A4 with a custom subset font whose CMap is
broken for the Hebrew labels (every Hebrew glyph extracts as a
private-use codepoint at ``size = 0``). The numeric and ASCII data,
however, lives in real text spans with ``size > 0`` and stable
``x``-coordinates, so a coordinate-based pdfplumber pass recovers
everything we need:

Globals (page-header band, y ≲ 140 pt)
    * RFQ number      — sz=10, x≈133–163, y≈55      (also in ``FAX_INFO:…``)
    * Issue date      — sz=8,  x≈251–295, y≈85
    * Buyer email     — sz=9,  x≈100–180, y≈100     (LDAP local-part)
    * Buyer phone     — sz=9,  x≈130–180, y≈88
    * Submission date — sz=10, dd/mm/yyyy on a later page

Locals (per delivery row, repeating per part block)
    * Quantity         — sz=9, x≈266–290     (``\\d+\\.\\d{2}``)
    * Day-offset (ARO) — sz=8, x≈358–372     (integer, days since ARO)
    * Delivery seq #   — sz=9, x≈400–405     (1..N within part)
    * ``N`` flag       — sz=9, x≈479–486     (not exported)
    * ``Each`` unit    — sz=9, x≈503–521
    * Description      — sz=9, x≥527
    * Rafael part #    — sz=8, x≈731–779     (alphanumeric all-caps)
    * Part seq index   — sz=9, x≈795–800
    * FAI marker       — sz=8, x≈30–48, ``FAI−`` then a digit just below

Per the V.5.1 spec the export TXT has eight tab-separated columns
(``\u05de\u05e1\u05e4\u05e8 \u05d1\u05dd\u05dc``, ``\u05e9\u05dd \u05e7\u05e0\u05d9\u05d9\u05df``,
``\u05ea\u05d0\u05e8\u05d9\u05da \u05e1\u05d5\u05e4\u05d9 \u05dc\u05d4\u05d2\u05e9\u05d4``,
``\u05de\u05e1\u05e4\u05e8 \u05e9\u05d5\u05e8\u05d4``,
``\u05de\u05e7\u05d8 \u05e8\u05e4\u05d0\u05dc``,
``\u05db\u05de\u05d5\u05ea \u05e0\u05d3\u05e8\u05e9\u05ea``,
``\u05ea\u05d0\u05e8\u05d9\u05da \u05d0\u05e1\u05e4\u05e7\u05d4 \u05e0\u05d3\u05e8\u05e9``,
``FAI``).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pdfplumber
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

FAI_NOT_REQUIRED = "לא נדרש"


class Delivery(BaseModel):
    quantity: float = Field(description="כמות נדרשת")
    delivery_date: str = Field(description="תאריך אספקה נדרש (dd/mm/yyyy)")
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
_EMAIL_Y = (95.0, 105.0)

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


def _offset_days_to_date(reference: date | None, offset: int) -> str:
    if reference is None:
        return ""
    d = reference + timedelta(days=offset)
    return d.strftime("%d/%m/%Y")


def _buyer_from_email(email: str) -> str:
    """Map ``haimka@rafael.co.il`` → ``HAIMKA`` (matches Rafael LDAP)."""
    if "@" not in email:
        return ""
    local = email.split("@", 1)[0].strip()
    return local.upper()


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


def _detect_buyer(pages: list[list[dict[str, Any]]]) -> str:
    for words in pages:
        for w in words:
            if not (_in_x(w, 0.0, _EMAIL_X_MAX)
                    and _EMAIL_Y[0] <= w["top"] <= _EMAIL_Y[1]):
                continue
            if "@rafael.co.il" in w["text"].lower():
                return _buyer_from_email(w["text"])
    return ""


def _detect_submission_date(
    pages: list[list[dict[str, Any]]],
    issue_date_str: str,
) -> str:
    """First ``dd/mm/yyyy`` token anywhere outside the page header.

    Falls back to the issue date if none is found.
    """
    for words in pages:
        for w in words:
            if w["top"] <= _HEADER_Y_MAX:
                continue
            if _RE_SUB_DATE.match(w["text"]):
                return w["text"]
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
    aro_ref: date | None,
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
                offset = int(offset_word["text"]) if offset_word else 0
                delivery_date = _offset_days_to_date(aro_ref, offset)

                fai = _find_fai_for_row(words, q["top"])
                block.deliveries.append(
                    Delivery(
                        quantity=quantity,
                        delivery_date=delivery_date,
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

    rfq_number = _detect_rfq_number(pages)
    issue_date = _detect_issue_date(pages)
    buyer_name = _detect_buyer(pages)
    submission_date = _detect_submission_date(pages, issue_date)

    aro_ref = _parse_dmy(submission_date) or _parse_dmy(issue_date)
    parts = _detect_part_blocks(pages, aro_ref)

    return RafaelRfq(
        rfq_number=rfq_number,
        buyer_name=buyer_name,
        submission_date=submission_date,
        parts=parts,
    )


# ---------------------------------------------------------------------------
# Row flattening + TSV writer (V.5.1 spec)
# ---------------------------------------------------------------------------

RAFAEL_TXT_COLUMNS: list[str] = [
    "מספר בלם",
    "שם קניין",
    "תאריך סופי להגשה",
    "מספר שורה",
    "מקט רפאל",
    "כמות נדרשת",
    "תאריך אספקה נדרש",
    "FAI",
]


def flatten_rafael_to_rows(rfq: RafaelRfq) -> list[dict[str, Any]]:
    """Flatten parts × deliveries into the 8-column row schema.

    Row numbers are globally sequential 1..N across the whole RFQ
    (not per-part), per the V.5.1 spec.
    """
    rows: list[dict[str, Any]] = []
    line_no = 0
    for part in rfq.parts:
        for d in part.deliveries:
            line_no += 1
            rows.append({
                "מספר בלם": rfq.rfq_number,
                "שם קניין": rfq.buyer_name,
                "תאריך סופי להגשה": rfq.submission_date,
                "מספר שורה": line_no,
                "מקט רפאל": part.rafael_pn,
                "כמות נדרשת": d.quantity,
                "תאריך אספקה נדרש": d.delivery_date,
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
# CLI test harness — `python parse_rafael_rfq.py <rfq.pdf> [<rfq.pdf> ...]`
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
