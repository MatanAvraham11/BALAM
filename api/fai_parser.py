"""
FAI (First Article Inspection) auto-ballooning for vector PDF engineering drawings.

Pipeline (pure PyMuPDF + stdlib, no LLM):
1. Extract text spans from every page.
2. Filter out border grid labels and title-block text.
3. Detect dimensions via regex (radius, diameter, angle, linear + tolerances).
4. Detect numbered notes from the NOTES section.
5. Classify each item and assign balloon numbers (notes first, then clockwise).
6. Draw semi-transparent balloons on the PDF.
7. Export a 5-column Hebrew CSV.
"""

from __future__ import annotations

import csv
import io
import math
import re
from pathlib import Path
from typing import Literal

import fitz  # PyMuPDF
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

DimensionType = Literal["Radius", "Diameter", "Angle", "Linear", "Note", "GeneralTolerance"]


class FAIItem(BaseModel):
    balloon_number: int = 0
    text: str
    dimension_type: DimensionType
    tolerance: str = ""
    page_index: int = 0
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)


class FAIResult(BaseModel):
    items: list[FAIItem] = Field(default_factory=list)
    page_sizes: list[tuple[float, float]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Annotation constants
# ---------------------------------------------------------------------------

CIRCLE_RADIUS = 10
CIRCLE_FILL = (1, 0.95, 0.4)
CIRCLE_STROKE = (0.8, 0.4, 0.0)
CIRCLE_FILL_OPACITY = 0.3
LABEL_COLOR = (0, 0, 0)
LABEL_FONTSIZE = 7
LABEL_MARGIN = 4.0

# Title-block exclusion zone (fraction of page dimensions)
_TITLE_BLOCK_X_FRAC = 0.62
_TITLE_BLOCK_Y_FRAC = 0.72

# Border margin for grid-label filtering (fraction of page dimensions)
_BORDER_MARGIN_FRAC = 0.03

# Fixed left-offset for note balloons (PDF user-space units ≈ points)
_NOTE_BALLOON_OFFSET_X = 20.0

# Maximum Y gap between consecutive note lines before collection stops
_NOTE_BREAK_Y = 60.0

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_RE_TOLERANCE_PM = re.compile(r"[±]\s*\d+(?:[.,]\d+)?")
_RE_TOLERANCE_ASYM = re.compile(
    r"\+\s*\d+(?:[.,]\d+)?\s*/\s*-\s*\d+(?:[.,]\d+)?"
)
_RE_RADIUS = re.compile(r"R\s*\d+(?:[.,]\d+)?", re.I)
_RE_DIAMETER = re.compile(r"(?:[⌀Øø]|DIA\.?)\s*\d+(?:[.,]\d+)?", re.I)
_RE_ANGLE = re.compile(r"\d+(?:[.,]\d+)?\s*°")
_RE_DIM_NUMBER = re.compile(r"\d+(?:[.,]\d+)")
_RE_NOTES_HEADER = re.compile(r"^\s*NOTES?\s*:?\s*$", re.I)
_RE_NOTE_BULLET = re.compile(r"^\s*(\d+)\s*[.)](?=\s|$)")
_RE_BORDER_LABEL = re.compile(r"^[A-Za-z0-9]$")
_RE_THREAD = re.compile(
    r"(?:"
    r"M\s*\d|"
    r"#\s*\d|"
    r"\bUN[CFJ][CF]?-?\s*\d|"
    r"\d+[/-]\d+\s*UN[A-Z]+"
    r")",
    re.I,
)

# Patterns that look like real dimension text (not just any number)
_RE_DIM_HINT = re.compile(
    r"("
    r"\d+[\d.,]*\s*[±+\-]|"
    r"[⌀Øø]|\bR\s*\d|\bR\.|"
    r"\d+\s*°|°\s*\d+|"
    r"#[\d\-]+|M\d|\bUN[CFJ][CF]?-?\s*\d|\bTHREAD\b|"
    r"\bRa\b|RZ|"
    r"TYP\.?|REF\.?|MAX\.?|MIN\.?|"
    r"\d+[\d.,]*\s*[xX]\s*\d+|"
    r"\d+[\d.,]{1,}\b"
    r")",
    re.I,
)

_RE_DOC_STAMP = re.compile(
    r"\b(UNCLASSIFIED|CLASSIFIED|CONFIDENTIAL|SECRET|RESTRICTED|"
    r"UNCONTROLLED|CONTROLLED|RELEASED|PROPRIETARY|ITAR|EAR)\b",
    re.I,
)

_RE_TOL_HEADER = re.compile(
    r"\b(?:GENERAL\s+TOLERANCES?|TOLERANCES?\s*:|UNLESS\s+OTHERWISE\s+SPECIFIED)",
    re.I,
)

_RE_GENTOL_LABEL = re.compile(r"^X(?:\.X{1,3})?$")
_RE_GENTOL_ANGLE = re.compile(r"^ANGLES?$", re.I)
_RE_GENTOL_VALUE = re.compile(r"^\s*[±]?\s*\d+(?:[.,]\d+)?\s*$")
_RE_GENTOL_NUM = re.compile(r"(\d+(?:[.,]\d+)?)")

_GENTOL_ROW_Y_THRESH = 5.0
_GENTOL_X_LEFT = 60.0   # max pt left of header x0 for label/value spans
_GENTOL_X_RIGHT = 200.0  # max pt right of header x0 for value spans


# ---------------------------------------------------------------------------
# Span extraction
# ---------------------------------------------------------------------------

class _Span:
    __slots__ = ("text", "bbox", "size", "page_index")

    def __init__(
        self, text: str, bbox: tuple[float, float, float, float],
        size: float, page_index: int,
    ) -> None:
        self.text = text
        self.bbox = bbox
        self.size = size
        self.page_index = page_index


def _extract_spans(page: fitz.Page, page_index: int) -> list[_Span]:
    spans: list[_Span] = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                t = span.get("text", "").strip()
                if not t:
                    continue
                b = span["bbox"]
                spans.append(
                    _Span(t, (b[0], b[1], b[2], b[3]), span.get("size", 0), page_index)
                )
    return spans


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

def _is_border_label(sp: _Span, pw: float, ph: float) -> bool:
    if not _RE_BORDER_LABEL.match(sp.text):
        return False
    cx = (sp.bbox[0] + sp.bbox[2]) / 2
    cy = (sp.bbox[1] + sp.bbox[3]) / 2
    mx = pw * _BORDER_MARGIN_FRAC
    my = ph * _BORDER_MARGIN_FRAC
    return cx < mx or cx > pw - mx or cy < my or cy > ph - my


def _is_in_title_block(sp: _Span, pw: float, ph: float) -> bool:
    cx = (sp.bbox[0] + sp.bbox[2]) / 2
    cy = (sp.bbox[1] + sp.bbox[3]) / 2
    return cx >= pw * _TITLE_BLOCK_X_FRAC and cy >= ph * _TITLE_BLOCK_Y_FRAC


def _find_tol_header(
    spans: list[_Span], page_index: int, ph: float,
) -> tuple[float, float] | None:
    """Return (x0, y) of the GENERAL TOLERANCES header on this page.

    Prefers a header in the lower half of the page (title-block region).
    Returns None if no header found.
    """
    best: tuple[float, float] | None = None
    for sp in spans:
        if sp.page_index != page_index:
            continue
        if not _RE_TOL_HEADER.search(sp.text):
            continue
        if best is None or sp.bbox[1] > 0.5 * ph:
            best = (sp.bbox[0], sp.bbox[1])
    return best


def _is_in_tolerance_block(
    sp: _Span, tol_hdr: tuple[float, float] | None,
) -> bool:
    """Check whether a span falls inside the GENERAL TOLERANCES region.

    Uses the header (x0, y) as anchor: spans must be below the header and
    within a horizontal band around the header's x position.
    """
    if tol_hdr is None:
        return False
    hdr_x0, hdr_y = tol_hdr
    return (
        sp.bbox[1] >= hdr_y
        and sp.bbox[0] >= hdr_x0 - _GENTOL_X_LEFT
        and sp.bbox[0] <= hdr_x0 + _GENTOL_X_RIGHT
    )


def _filter_spans(
    spans: list[_Span], pw: float, ph: float,
) -> list[_Span]:
    return [
        sp for sp in spans
        if not _is_border_label(sp, pw, ph) and not _is_in_title_block(sp, pw, ph)
    ]


# ---------------------------------------------------------------------------
# GENERAL TOLERANCES parser
# ---------------------------------------------------------------------------

def _parse_general_tolerances(
    raw_spans: list[_Span],
    page_index: int,
    tol_hdr: tuple[float, float] | None,
) -> list[FAIItem]:
    """Extract tolerance values from the GENERAL TOLERANCES block.

    Groups spans into rows by Y proximity, then for each row that contains
    a known label (X, X.X, X.XX, X.XXX, or ANGLES) AND a numeric value to
    its right, produces a single FAIItem on the value span.  Rows with a
    label but no numeric value (e.g. bare "X") are skipped.
    """
    if tol_hdr is None:
        return []

    block_spans = [
        sp for sp in raw_spans
        if sp.page_index == page_index and _is_in_tolerance_block(sp, tol_hdr)
    ]
    if not block_spans:
        return []

    block_spans.sort(key=lambda s: (s.bbox[1] + s.bbox[3]) / 2)

    rows: list[list[_Span]] = []
    current_row: list[_Span] = [block_spans[0]]

    for sp in block_spans[1:]:
        cy = (sp.bbox[1] + sp.bbox[3]) / 2
        prev_cy = (current_row[-1].bbox[1] + current_row[-1].bbox[3]) / 2
        if abs(cy - prev_cy) <= _GENTOL_ROW_Y_THRESH:
            current_row.append(sp)
        else:
            rows.append(current_row)
            current_row = [sp]
    rows.append(current_row)

    items: list[FAIItem] = []
    for row in rows:
        row.sort(key=lambda s: s.bbox[0])

        label_x2 = 0.0
        has_label = False
        for sp in row:
            if _RE_GENTOL_LABEL.match(sp.text) or _RE_GENTOL_ANGLE.match(sp.text):
                has_label = True
                label_x2 = sp.bbox[2]
                break

        if not has_label:
            continue

        for sp in row:
            if sp.bbox[0] < label_x2:
                continue
            if _RE_GENTOL_VALUE.match(sp.text):
                m = _RE_GENTOL_NUM.search(sp.text)
                items.append(FAIItem(
                    text=m.group(1) if m else sp.text.strip(),
                    dimension_type="GeneralTolerance",
                    tolerance="",
                    page_index=page_index,
                    bbox=sp.bbox,
                ))
                break

    return items


# ---------------------------------------------------------------------------
# NOTES parser
# ---------------------------------------------------------------------------

def _parse_notes(spans: list[_Span], page_index: int) -> list[FAIItem]:
    """Find NOTES / NOTES: header and collect numbered lines strictly below it."""
    header_bbox: tuple[float, float, float, float] | None = None
    for sp in spans:
        if sp.page_index == page_index and _RE_NOTES_HEADER.match(sp.text):
            header_bbox = sp.bbox
            break
    if header_bbox is None:
        return []

    below = sorted(
        [
            sp
            for sp in spans
            if sp.page_index == page_index and sp.bbox[1] >= header_bbox[3]
        ],
        key=lambda s: (s.bbox[1], s.bbox[0]),
    )

    notes: list[FAIItem] = []
    prev_bottom = header_bbox[3]

    for sp in below:
        if sp.bbox[1] - prev_bottom > _NOTE_BREAK_Y:
            break
        m = _RE_NOTE_BULLET.match(sp.text)
        if m:
            notes.append(
                FAIItem(
                    text=sp.text.strip(),
                    dimension_type="Note",
                    tolerance="",
                    page_index=page_index,
                    bbox=sp.bbox,
                )
            )
        prev_bottom = sp.bbox[3]

    return notes


# ---------------------------------------------------------------------------
# Dimension detection & classification
# ---------------------------------------------------------------------------

def _extract_tolerance(text: str) -> tuple[str, str]:
    """Return (nominal_text, tolerance_string). Strip tolerance from text."""
    m = _RE_TOLERANCE_PM.search(text)
    if m:
        tol = m.group(0).strip()
        nominal = text[: m.start()].strip() + text[m.end() :].strip()
        return nominal.strip(), tol
    m = _RE_TOLERANCE_ASYM.search(text)
    if m:
        tol = m.group(0).strip()
        nominal = text[: m.start()].strip() + text[m.end() :].strip()
        return nominal.strip(), tol
    return text.strip(), ""


def _classify(text: str) -> DimensionType | None:
    if _RE_RADIUS.search(text):
        return "Radius"
    if _RE_DIAMETER.search(text):
        return "Diameter"
    if _RE_ANGLE.search(text):
        return "Angle"
    if _RE_THREAD.search(text):
        return "Linear"
    if _RE_DIM_NUMBER.search(text):
        return "Linear"
    return None


def _looks_like_dimension(text: str) -> bool:
    return bool(_RE_DIM_HINT.search(text))


def _detect_dimensions(spans: list[_Span], note_bboxes: set[tuple[float, float, float, float]]) -> list[FAIItem]:
    items: list[FAIItem] = []
    for sp in spans:
        if sp.bbox in note_bboxes:
            continue
        if _RE_DOC_STAMP.search(sp.text):
            continue
        if not _looks_like_dimension(sp.text):
            continue
        nominal, tolerance = _extract_tolerance(sp.text)
        dim_type = _classify(nominal)
        if dim_type is None:
            continue
        items.append(FAIItem(
            text=nominal,
            dimension_type=dim_type,
            tolerance=tolerance,
            page_index=sp.page_index,
            bbox=sp.bbox,
        ))
    return items


# ---------------------------------------------------------------------------
# Numbering: unified clockwise
# ---------------------------------------------------------------------------

def _clockwise_angle(cx: float, cy: float, x: float, y: float) -> float:
    """Angle from 12-o'clock position, increasing clockwise (0..2pi)."""
    dx = x - cx
    dy = y - cy
    angle = math.atan2(dx, -dy)  # 0 = up, positive = clockwise
    if angle < 0:
        angle += 2 * math.pi
    return angle


def _assign_numbers(
    notes: list[FAIItem],
    dims: list[FAIItem],
    page_sizes: list[tuple[float, float]],
) -> list[FAIItem]:
    def _sort_key(it: FAIItem) -> tuple[int, float]:
        pw, ph = page_sizes[it.page_index] if it.page_index < len(page_sizes) else (1, 1)
        cx_page, cy_page = pw / 2, ph / 2
        ix = (it.bbox[0] + it.bbox[2]) / 2
        iy = (it.bbox[1] + it.bbox[3]) / 2
        return (it.page_index, _clockwise_angle(cx_page, cy_page, ix, iy))

    combined = sorted(notes + dims, key=_sort_key)
    for i, item in enumerate(combined, start=1):
        item.balloon_number = i
    return combined


# ---------------------------------------------------------------------------
# Balloon annotation
# ---------------------------------------------------------------------------

def _rects_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def _place_balloon_center(
    item_bbox: tuple[float, float, float, float],
    all_text_bboxes: list[tuple[float, float, float, float]],
    pw: float,
    ph: float,
) -> tuple[float, float]:
    """Find a balloon centre that does not overlap any text bbox on the page."""
    x0, y0, x1, y1 = item_bbox
    mcx = (x0 + x1) / 2
    mcy = (y0 + y1) / 2
    eff = CIRCLE_RADIUS + 2.0
    base = max((x1 - x0) * 0.5 + CIRCLE_RADIUS + 6, 18.0)

    best: tuple[float, float] | None = None
    best_score = float("inf")

    for itry in range(1, 100):
        radius = base + itry * 1.5
        for a in range(8):
            ang = a * (2 * math.pi / 8) - math.pi / 2
            cx = mcx + radius * math.cos(ang)
            cy = mcy + radius * math.sin(ang)
            cx = max(eff, min(pw - eff, cx))
            cy = max(eff, min(ph - eff, cy))
            cb = (cx - eff, cy - eff, cx + eff, cy + eff)

            hit = False
            total_inter = 0.0
            for tb in all_text_bboxes:
                if _rects_overlap(cb, tb):
                    hit = True
                    ix = max(0.0, min(cb[2], tb[2]) - max(cb[0], tb[0]))
                    iy = max(0.0, min(cb[3], tb[3]) - max(cb[1], tb[1]))
                    total_inter += ix * iy
            if _rects_overlap(cb, item_bbox):
                hit = True

            if not hit:
                return (cx, cy)

            dist = (cx - mcx) ** 2 + (cy - mcy) ** 2
            score = total_inter * 500.0 + dist
            if score < best_score:
                best_score = score
                best = (cx, cy)

    return best if best is not None else (max(eff, mcx + base), max(eff, mcy - base))


def _annotate_pdf(
    doc: fitz.Document,
    items: list[FAIItem],
    page_text_bboxes: list[list[tuple[float, float, float, float]]],
) -> bytes:
    for item in items:
        if item.page_index >= len(doc):
            continue
        page = doc[item.page_index]
        pw, ph = page.rect.width, page.rect.height
        bboxes = page_text_bboxes[item.page_index] if item.page_index < len(page_text_bboxes) else []
        if item.dimension_type == "Note":
            cx = item.bbox[0] - _NOTE_BALLOON_OFFSET_X
            cy = (item.bbox[1] + item.bbox[3]) / 2
            eff = CIRCLE_RADIUS + 2.0
            cx = max(eff, min(pw - eff, cx))
            cy = max(eff, min(ph - eff, cy))
        else:
            cx, cy = _place_balloon_center(item.bbox, bboxes, pw, ph)

        shape = page.new_shape()
        shape.draw_circle(fitz.Point(cx, cy), CIRCLE_RADIUS)
        shape.finish(
            color=CIRCLE_STROKE,
            fill=CIRCLE_FILL,
            width=0.8,
            fill_opacity=CIRCLE_FILL_OPACITY,
        )
        shape.commit()

        label = str(item.balloon_number)
        text_point = fitz.Point(
            cx - len(label) * (LABEL_FONTSIZE * 0.3),
            cy + LABEL_FONTSIZE * 0.35,
        )
        page.insert_text(
            text_point,
            label,
            fontsize=LABEL_FONTSIZE,
            color=LABEL_COLOR,
            fontname="helv",
        )

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

_CSV_HEADERS = ["מספר בלון", "מידה / הערה", "סוג מידה", "טולרנס", "נמצא"]


def items_to_csv(items: list[FAIItem]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_ALL)
    writer.writerow(_CSV_HEADERS)
    for it in items:
        writer.writerow([it.balloon_number, it.text, it.dimension_type, it.tolerance, ""])
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_fai(pdf_path: str | Path) -> tuple[FAIResult, bytes]:
    """Parse a vector PDF, return FAI items and annotated PDF bytes."""
    pdf_path = Path(pdf_path)
    doc = fitz.open(str(pdf_path))
    page_sizes: list[tuple[float, float]] = []
    all_notes: list[FAIItem] = []
    all_dims: list[FAIItem] = []
    page_text_bboxes: list[list[tuple[float, float, float, float]]] = []

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        pw, ph = page.rect.width, page.rect.height
        page_sizes.append((pw, ph))

        raw_spans = _extract_spans(page, page_idx)
        page_text_bboxes.append([sp.bbox for sp in raw_spans])
        spans = _filter_spans(raw_spans, pw, ph)

        tol_hdr = _find_tol_header(raw_spans, page_idx, ph)
        tol_items = _parse_general_tolerances(raw_spans, page_idx, tol_hdr)
        spans = [sp for sp in spans if not _is_in_tolerance_block(sp, tol_hdr)]

        notes = _parse_notes(spans, page_idx)
        note_bboxes = {n.bbox for n in notes}

        dims = _detect_dimensions(spans, note_bboxes)

        all_notes.extend(notes)
        all_dims.extend(dims)
        all_dims.extend(tol_items)

    items = _assign_numbers(all_notes, all_dims, page_sizes)
    result = FAIResult(items=items, page_sizes=page_sizes)

    annotated_bytes = _annotate_pdf(doc, items, page_text_bboxes)
    doc.close()
    return result, annotated_bytes


# ---------------------------------------------------------------------------
# CLI test harness
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python fai_parser.py <drawing.pdf>")
        sys.exit(1)

    pdf = Path(sys.argv[1])
    if not pdf.exists():
        print(f"File not found: {pdf}")
        sys.exit(1)

    result, annotated = run_fai(pdf)
    out_pdf = pdf.with_name(pdf.stem + "_annotated.pdf")
    out_csv = pdf.with_name(pdf.stem + "_fai.csv")
    out_pdf.write_bytes(annotated)
    out_csv.write_text(items_to_csv(result.items), encoding="utf-8-sig")
    print(f"Wrote {out_pdf} and {out_csv} ({len(result.items)} items)")
