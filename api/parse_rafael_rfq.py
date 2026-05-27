"""
Rafael BOM (RFQ) parser — V.5.9.

Rafael RFQ PDFs are landscape A4 with a custom subset font whose CMap is
broken for the Hebrew labels (every Hebrew glyph extracts as a
private-use codepoint at ``size = 0``). The numeric and ASCII data,
however, lives in real text spans with ``size > 0`` and stable
``x``-coordinates, so a coordinate-based pdfplumber pass recovers
everything we need:

Globals (page-header band, y ≲ 140 pt)
    * RFQ number      — sz=10, x≈133–163, y≈55      (also in ``FAX_INFO:…``)
    * Issue date      — sz=8,  x≈251–295, y≈85
    * Buyer name      — **V.5.9:** deterministic OCR only: pdfplumber finds the
      ``…@rafael.co.il`` anchor on page 1; **PyMuPDF** renders a **300 DPI**
      **surgical** clip (``x0−15 … x1+2``, ``top−27 … top−13``) that frames ONLY
      the buyer-name glyphs. The crop is calibrated against PUA glyph positions:
      buyer-name characters live at ``x≈115–180pt`` while the ``קניין:`` label
      sits at ``x≈189–206pt``; ``clip_x1 = email.x1 + 2`` cuts cleanly between
      them. The neighbour cells (``תאריך הדפסה`` above, phone row below) are
      excluded by the y-band. The crop is sent to **OCR.space** as **multipart**
      ``file=`` (JPEG) with ``language=heb``/``auto`` on Engine **3** then **2**
      (``OCR_SPACE_API_KEY``). Because the OCR now receives a pure-name image,
      ``_buyer_ocr_label_clean`` is minimal: strip non-Hebrew chars, collapse
      whitespace, take the longest Hebrew run, and drop 1-letter edge tokens
      (residual noise). ``_hebrew_letter_count`` (U+05D0–U+05EA) must be ≥2 or
      the buyer field is left empty (no e-mail map).
      There is **no** hardcoded buyer dictionary and **no** e-mail local-part
      fallback. If the anchor or OCR output is unusable (fewer than two Hebrew
      letters after cleaning), the buyer field is ``""``.
      Set ``RAFAEL_BUYER_OCR=0`` to disable OCR (still returns ``"OCR Failed"``;
      the HTTP API adds ``buyer_ocr_ready`` / ``buyer_ocr_reason`` from
      ``rafael_buyer_ocr_api_status()`` (env probe plus parse-time codes such as
      ``ocr_space_no_hebrew`` when the key is set but OCR text is too weak).
      Set ``RAFAEL_OCR_DEBUG=1`` to write the exact crop sent to OCR.space to
      ``debug_crop.png`` (override path with ``RAFAEL_OCR_DEBUG_PATH``).
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

import io
import os
import re
import time
import warnings
from datetime import date, datetime
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

# V.5.9 buyer-name OCR — SURGICAL crop (calibrated against 3 reference Rafael RFQs).
# Goal: feed OCR.space ONLY the buyer-name glyphs — no "קניין:" label, no neighbor
# cells (date/phone), no borders. With a pure-name image we can drop all of the
# label-stripping junk-phrase regex.
#
# Calibration (PUA glyph positions from pdfplumber on 3 PDFs):
#   - Buyer-name characters span x ≈ 115–180pt (longest name "שירן סורני שלאם").
#   - "קניין:" label characters span x ≈ 189–206pt (consistent across PDFs).
#   - Email anchor: x0 ≈ 100–104, x1 ≈ 180.7–180.8, top ≈ 100.3.
#   - Buyer-name row Hebrew glyphs centred at top ≈ 82.9 (band ≈ 78–87pt).
#
# Crop coordinates (relative to email anchor `e`):
#   clip_x0 = e.x0 - 15      → ≈ 85–89pt (leftmost name char ~115; safe margin)
#   clip_x1 = e.x1 + 2       → ≈ 183pt   (right of name end 176pt, LEFT of label start 189pt)
#   clip_y0 = e.top - 27     → ≈ 73pt    (+5pt headroom above name glyphs at top≈83)
#   clip_y1 = e.top - 13     → ≈ 87pt    (above phone row at top=88)
_BUYER_CROP_PAD_X0_LEFT = 15.0
_BUYER_CROP_X1_PAD_RIGHT = 2.0
_BUYER_CROP_DELTA_TOP = 27.0
_BUYER_CROP_DELTA_BOTTOM = 13.0
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


def _hebrew_letter_count(text: str) -> int:
    """Count characters in the Hebrew letter range U+05D0–U+05EA (Aleph–Tav)."""
    return sum(1 for c in text if "\u05d0" <= c <= "\u05ea")


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
# V.5.9 — Buyer name: PyMuPDF geometric crop + OCR.space API (language=heb)
# ---------------------------------------------------------------------------

_OCR_SPACE_URL = "https://api.ocr.space/parse/image"
# Free OCR.space tier payload limit is ~1 MB; stay safely under.
_OCR_SPACE_MAX_IMAGE_BYTES = 950_000

# Transient HTTP statuses: retry before treating the OCR attempt as failed.
_OCR_SPACE_RETRYABLE_HTTP: frozenset[int] = frozenset({
    408, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524,
})

# Set during ``parse_rafael_rfq`` / buyer OCR for ``rafael_buyer_ocr_api_status`` (UI / API).
_RAFAEL_LAST_OCR_PARSE_REASON: str | None = None
# Last non-OK HTTP status from OCR.space (when ``buyer_ocr_reason`` is HTTP-related); ``None`` if N/A.
_RAFAEL_LAST_OCR_HTTP_STATUS: int | None = None


def _reset_rafael_buyer_ocr_parse_reason() -> None:
    global _RAFAEL_LAST_OCR_PARSE_REASON, _RAFAEL_LAST_OCR_HTTP_STATUS
    _RAFAEL_LAST_OCR_PARSE_REASON = None
    _RAFAEL_LAST_OCR_HTTP_STATUS = None


def rafael_buyer_ocr_api_status() -> dict[str, Any]:
    """``buyer_ocr_ready`` / ``buyer_ocr_reason`` for HTTP responses after a parse.

    When the env stack is ready but the buyer field is still empty, ``reason`` may
    be ``ocr_space_no_hebrew`` or ``ocr_space_parse_empty`` (set during parse).
    ``buyer_ocr_http_status`` is set when the failure was classified from an HTTP
    status (not connection-only).
    """
    ready, base = _rafael_buyer_ocr_probe()
    out: dict[str, Any] = {}
    if not ready:
        out["ready"] = False
        out["reason"] = base
    else:
        out["ready"] = True
        out["reason"] = _RAFAEL_LAST_OCR_PARSE_REASON
    hs = _RAFAEL_LAST_OCR_HTTP_STATUS
    if hs is not None:
        out["buyer_ocr_http_status"] = hs
    return out


def _rafael_buyer_ocr_probe() -> tuple[bool, str | None]:
    """Return ``(ready, reason_code)`` for Rafael buyer OCR via OCR.space.

    ``reason_code`` is a stable machine string for API/UI; ``None`` when ready.
    """
    if os.environ.get("RAFAEL_BUYER_OCR", "").strip().lower() in (
        "0", "false", "no", "off",
    ):
        return False, "rafael_buyer_ocr_disabled"
    if not (os.environ.get("OCR_SPACE_API_KEY") or "").strip():
        return False, "ocr_space_api_key_missing"
    try:
        import requests  # noqa: PLC0415, F401
    except ImportError:
        return False, "requests_import_failed"
    return True, None


def _tesseract_hebrew_ready() -> bool:
    """Compatibility name (V.5.7): True when OCR.space buyer OCR is configured (V.5.9)."""
    ok, _reason = _rafael_buyer_ocr_probe()
    return ok


def rafael_buyer_ocr_diagnostic() -> dict[str, Any]:
    """Structured OCR environment status for API responses (no secrets)."""
    ok, reason = _rafael_buyer_ocr_probe()
    return {"ready": ok, "reason": reason}


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


def _strip_short_edge_tokens(hebrew_line: str) -> str:
    """Drop single-letter Hebrew "words" at the start/end of the buyer line.

    Real Hebrew names always have ≥2 letters per component (e.g. ``בן``, ``בר``,
    ``אל``); standalone one-letter tokens at the edge are residual OCR noise
    (e.g. a stray glyph from a cell border, or a soft hyphen). Stripping only
    one-letter words at the edges is safe.
    """
    parts = hebrew_line.split()
    while parts and len(parts[0]) == 1:
        parts.pop(0)
    while parts and len(parts[-1]) == 1:
        parts.pop()
    return " ".join(parts).strip()


def _buyer_ocr_label_clean(raw: str) -> str:
    """Normalize OCR output of the surgical buyer-name crop.

    Since V.5.9 the crop is surgically calibrated to contain ONLY the buyer-name
    glyphs (no ``קניין:`` label, no neighbor cells), so cleaning is now minimal:
    drop non-Hebrew characters (stray punctuation, soft hyphens, digit artefacts),
    collapse whitespace, take the longest Hebrew-only span (defensive guard
    against single rogue characters), and strip 1-letter tokens at the edges.
    """
    s = (raw or "").replace("\n", " ").replace("\r", " ")
    s = re.sub(r"[^\u0590-\u05FF\s]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return ""
    runs = re.findall(r"[\u0590-\u05FF]+(?:\s+[\u0590-\u05FF]+)*", s)
    if not runs:
        return s
    best = max(runs, key=lambda t: (_hebrew_letter_count(t), len(t)))
    best = _strip_short_edge_tokens(best)
    return best.strip()


def _pil_jpeg_bytes_under_limit(img: Image.Image, max_bytes: int = _OCR_SPACE_MAX_IMAGE_BYTES) -> bytes:
    """Encode crop as JPEG, shrinking if needed for OCR.space free-tier size limits."""
    rgb = img.convert("RGB")
    w, h = rgb.size
    for factor in (1.0, 0.85, 0.7, 0.55, 0.4, 0.3, 0.22, 0.16):
        im = rgb if factor >= 0.999 else rgb.resize(
            (max(8, int(w * factor)), max(8, int(h * factor))),
            Image.Resampling.LANCZOS,
        )
        for quality in (92, 85, 78, 70, 62, 55):
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=quality, optimize=True)
            data = buf.getvalue()
            if len(data) <= max_bytes:
                return data
    buf = io.BytesIO()
    rgb.resize((max(8, int(w * 0.14)), max(8, int(h * 0.14))), Image.Resampling.LANCZOS).save(
        buf, format="JPEG", quality=60, optimize=True,
    )
    return buf.getvalue()


def _ocr_space_collect_parsed_text(payload: dict[str, Any]) -> str:
    """Join ``ParsedResults[].ParsedText`` from OCR.space JSON.

    Prefer returning any non-empty ``ParsedText`` even when ``OCRExitCode`` is
    not 1/2 (Engine 3 / edge cases), as long as the block-level parse code is OK.
    """
    if not isinstance(payload, dict):
        return ""
    chunks: list[str] = []
    for block in payload.get("ParsedResults") or []:
        if not isinstance(block, dict):
            continue
        fpe = block.get("FileParseExitCode")
        if fpe is not None:
            try:
                if int(fpe) < 0:
                    continue
            except (TypeError, ValueError):
                pass
        txt = block.get("ParsedText")
        if txt:
            chunks.append(str(txt).strip())
    return "\n".join(chunks).strip()


def _buyer_name_from_ocr_space(
    pdf_path: Path,
    email_w: dict[str, Any],
) -> tuple[str, str | None]:
    """V.5.9 crop → JPEG → OCR.space. Hebrew is supported on **Engine 3** (see OCR.space docs).

    Returns ``(cleaned_text, failure_reason)``. ``failure_reason`` is ``None`` when
    the cleaned text has at least two Hebrew letters; otherwise a stable code for
    ``rafael_buyer_ocr_api_status``.
    """
    global _RAFAEL_LAST_OCR_HTTP_STATUS
    import requests  # noqa: PLC0415

    _RAFAEL_LAST_OCR_HTTP_STATUS = None

    api_key = (os.environ.get("OCR_SPACE_API_KEY") or "").strip()
    if not api_key:
        return "", None

    x0 = float(email_w["x0"])
    x1 = float(email_w["x1"])
    etop = float(email_w["top"])
    clip_x0 = max(0.0, x0 - _BUYER_CROP_PAD_X0_LEFT)
    clip_x1 = x1 + _BUYER_CROP_X1_PAD_RIGHT
    clip_y0 = etop - _BUYER_CROP_DELTA_TOP
    clip_y1 = etop - _BUYER_CROP_DELTA_BOTTOM

    rect = fitz.Rect(clip_x0, clip_y0, clip_x1, clip_y1)
    if rect.is_empty or rect.width <= 0 or rect.height <= 0:
        return "", "ocr_space_parse_empty"

    doc = fitz.open(pdf_path)
    try:
        page = doc[0]
        clip = rect & page.rect
        if clip.is_empty:
            return "", "ocr_space_parse_empty"
        zoom = _BUYER_OCR_DPI / 72.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
    finally:
        doc.close()

    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    if os.environ.get("RAFAEL_OCR_DEBUG", "").strip().lower() in ("1", "true", "yes", "on"):
        # Persist the exact image sent to OCR.space so a human can visually verify
        # that the surgical crop excludes the "קניין:" label and neighbor cells.
        debug_path = Path(os.environ.get("RAFAEL_OCR_DEBUG_PATH") or "debug_crop.png")
        try:
            img.save(debug_path)
            warnings.warn(
                f"Rafael buyer OCR: debug crop saved to {debug_path} "
                f"(rect={clip_x0:.1f},{clip_y0:.1f},{clip_x1:.1f},{clip_y1:.1f}).",
                UserWarning,
                stacklevel=2,
            )
        except OSError as exc:
            warnings.warn(
                f"Rafael buyer OCR: failed to save debug_crop.png: {exc}",
                UserWarning,
                stacklevel=2,
            )

    jpeg_bytes = _pil_jpeg_bytes_under_limit(img)

    best_clean = ""
    best_hc = -1
    n_posts = 0
    n_http_bad = 0
    n_json_bad = 0
    saw_nonempty_raw = False
    http_fail_statuses: list[int] = []
    quota_api_body: list[bool] = []
    ocr_debug = os.environ.get("RAFAEL_OCR_DEBUG", "").strip().lower() in (
        "1", "true", "yes", "on",
    )
    from requests import exceptions as req_exc  # noqa: PLC0415

    def one_call(language: str, engine: str) -> None:
        """One OCR.space call using multipart file upload (recommended by OCR.space docs).

        Note: ``base64Image`` requires the ``data:image/jpeg;base64,`` data-URI prefix
        or the server returns HTTP 400 ("Not a valid base64 image"). Multipart ``file``
        avoids the prefix gotcha and is ~33% smaller on the wire.
        """
        nonlocal best_clean, best_hc, n_posts, n_http_bad, n_json_bad, saw_nonempty_raw
        n_posts += 1
        r: Any = None
        for attempt in range(3):
            if attempt:
                time.sleep(0.7 * (2 ** (attempt - 1)))
            try:
                r = requests.post(
                    _OCR_SPACE_URL,
                    data={
                        "apikey": api_key,
                        "language": language,
                        "isOverlayRequired": "false",
                        "scale": "true",
                        "OCREngine": engine,
                    },
                    files={
                        "file": ("buyer.jpg", jpeg_bytes, "image/jpeg"),
                    },
                    timeout=90,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (compatible; BalamRafael/1.0; "
                            "+https://github.com/MatanAvraham11/BALAM)"
                        ),
                    },
                )
            except (req_exc.ConnectionError, req_exc.Timeout, OSError):
                r = None
                if attempt == 2:
                    n_http_bad += 1
                    http_fail_statuses.append(0)
                    if ocr_debug:
                        warnings.warn(
                            f"OCR.space: connection/timeout after 3 tries "
                            f"(lang={language} engine={engine})",
                            UserWarning,
                            stacklevel=3,
                        )
                    return
                continue

            if r.ok:
                break

            if r.status_code in _OCR_SPACE_RETRYABLE_HTTP and attempt < 2:
                continue

            n_http_bad += 1
            http_fail_statuses.append(r.status_code)
            if ocr_debug:
                warnings.warn(
                    f"OCR.space HTTP {r.status_code} for engine={engine} lang={language}",
                    UserWarning,
                    stacklevel=3,
                )
            return

        assert r is not None and r.ok
        try:
            payload = r.json()
        except ValueError:
            n_json_bad += 1
            return
        raw = _ocr_space_collect_parsed_text(payload)
        if raw:
            saw_nonempty_raw = True
        else:
            em = str(payload.get("ErrorMessage") or "").strip().lower()
            if em and any(
                s in em
                for s in (
                    "credit", "quota", "maximum", "daily",
                    "subscription", "not enough",
                )
            ):
                quota_api_body.append(True)
        if ocr_debug and not raw:
            warnings.warn(
                "OCR.space debug: "
                f"status={r.status_code} OCRExitCode={payload.get('OCRExitCode')!r} "
                f"IsErrored={payload.get('IsErroredOnProcessing')!r} "
                f"ErrorMessage={payload.get('ErrorMessage')!r}",
                UserWarning,
                stacklevel=3,
            )
        clean = _buyer_ocr_label_clean(raw)
        hc = _hebrew_letter_count(clean)
        if hc > best_hc or (hc == best_hc and len(clean) > len(best_clean)):
            best_hc = hc
            best_clean = clean

    # OCR.space: Hebrew is supported on Engine 3 only; Engine 1 rejects
    # language=heb / language=auto with HTTP 400. Engine 2 supports auto-detect.
    one_call("heb", "3")
    if best_hc >= 2:
        return best_clean, None
    one_call("auto", "3")
    if best_hc >= 2:
        return best_clean, None
    one_call("auto", "2")
    if best_hc >= 2:
        return best_clean, None

    if best_hc >= 2:
        return best_clean, None
    if best_clean:
        return best_clean, "ocr_space_no_hebrew"
    if n_posts and n_http_bad == n_posts and http_fail_statuses:
        nz = [c for c in http_fail_statuses if c != 0]
        if not nz:
            return "", "ocr_space_network_error"
        _RAFAEL_LAST_OCR_HTTP_STATUS = nz[0]
        if all(c in (401, 403) for c in nz):
            return "", "ocr_space_auth_error"
        if any(c == 429 for c in nz):
            return "", "ocr_space_rate_limited"
        if any(c in (413, 414) for c in nz):
            return "", "ocr_space_payload_too_large"
        if any(c == 400 for c in nz):
            return "", "ocr_space_bad_request"
        if any(c >= 500 for c in nz):
            return "", "ocr_space_server_error"
        if any(400 <= c < 500 for c in nz):
            return "", "ocr_space_client_error"
        return "", "ocr_space_http_error"
    if n_posts and n_json_bad == n_posts and not saw_nonempty_raw:
        return "", "ocr_space_json_error"
    if quota_api_body and not best_clean:
        return "", "ocr_space_quota_exceeded"
    return "", "ocr_space_parse_empty"


def _detect_buyer(pdf_path: Path, pages: list[list[dict[str, Any]]]) -> str:
    """Buyer Hebrew name: OCR path only; no e-mail dictionary or local-part fallback."""
    global _RAFAEL_LAST_OCR_PARSE_REASON
    _RAFAEL_LAST_OCR_PARSE_REASON = None
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
            "Rafael buyer OCR unavailable: set OCR_SPACE_API_KEY or disable with RAFAEL_BUYER_OCR=0.",
            UserWarning,
            stacklevel=2,
        )
        return "OCR Failed"
    clean_name, ocr_sub = _buyer_name_from_ocr_space(pdf_path, email_w)
    _RAFAEL_LAST_OCR_PARSE_REASON = ocr_sub
    if _hebrew_letter_count(clean_name) >= 2:
        _RAFAEL_LAST_OCR_PARSE_REASON = None
        return clean_name
    if clean_name:
        warnings.warn(
            f"Rafael buyer OCR: insufficient Hebrew letters in cleaned output ({clean_name!r}).",
            UserWarning,
            stacklevel=2,
        )
    return ""


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
    _reset_rafael_buyer_ocr_parse_reason()
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
