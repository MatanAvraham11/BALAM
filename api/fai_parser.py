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
_BALLOON_GAP = 2.0  # extra clearance between balloons (PDF pt)

# Span merging: a dimension and its tolerance are often two adjacent spans.
_DIM_MERGE_Y_TOL = 1.5      # max diff between vertical centers (pt)
_DIM_MERGE_GAP_X = 6.0      # max horizontal gap between spans (pt)

# Leader line: thin black stroke from balloon rim to nearest point on dimension bbox when balloon sits far from item centre.
_LEADER_LINE_WIDTH = 0.4
_LEADER_LINE_COLOR = (0.0, 0.0, 0.0)
_LEADER_DISTANCE_FROM_CENTER_MULT = 2.5  # leader if ‖(cx,cy)-(mcx,mcy)‖ > CIRCLE_RADIUS × this

# Vector-graphics avoidance — balloon scoring weights (overlap areas × weight).
_TEXT_OVERLAP_WEIGHT = 500.0       # text / own dimension / other balloons (hard)
_DRAWING_OVERLAP_WEIGHT = 300.0    # vector strokes — strict penalty

# Grid search: expand item_bbox by MAX_DIST on every side (anchored to dimension, not only mcx/mcy).
_GRID_EXPAND_FACTOR = 6.0          # MAX_DIST = factor × CIRCLE_RADIUS
_GRID_STEP_DIVISOR = 2.0          # step = CIRCLE_RADIUS / divisor (half-radius spacing)

# Engineer-style snap: balloon centre shares the horizontal band OR vertical band of the dimension bbox.
_EDGE_BAND_BONUS = -500.0         # when (y0≤cy≤y1) or (x0≤cx≤x1)

# Drawings whose bbox is essentially the page border (engineering frame).
_PAGE_BORDER_W_FRAC = 0.90        # ≥ 90% of page width …
_PAGE_BORDER_H_FRAC = 0.90       # …and ≥ 90% of page height → reject (single rect)
_DRAWING_MIN_DIM = 0.5           # ignore degenerate / zero-size paths
_DRAWING_PADDING = 0.5           # widen thin lines so ``cb`` intersects strokes

# Debug overlay colours (stroke RGB 0–1 for ``shape.finish``).
_DEBUG_TEXT_STROKE = (0.15, 0.35, 1.0)      # blue — detected text spans
_DEBUG_DRAWING_STROKE = (1.0, 0.15, 0.05)   # red — detected drawing bboxes

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


def _merge_dim_spans(spans: list[_Span]) -> list[_Span]:
    """Merge horizontally adjacent spans that share a vertical baseline.

    Engineering drawings frequently split a dimension and its tolerance
    into two separate text spans (e.g. ``"10.5"`` and ``"±0.1"``). Treating
    them as a single ``FAIItem`` lets the rest of the pipeline classify
    correctly and lets the balloon placer use a unified bbox so the leader
    points at the full dimension instead of just the nominal half.
    """
    if not spans:
        return spans

    sorted_spans = sorted(
        spans,
        key=lambda s: (s.page_index, (s.bbox[1] + s.bbox[3]) / 2, s.bbox[0]),
    )

    out: list[_Span] = []
    cur: _Span | None = None

    for sp in sorted_spans:
        if cur is None:
            cur = sp
            continue

        cy_a = (cur.bbox[1] + cur.bbox[3]) / 2
        cy_b = (sp.bbox[1] + sp.bbox[3]) / 2
        same_line = (
            sp.page_index == cur.page_index
            and abs(cy_a - cy_b) <= _DIM_MERGE_Y_TOL
        )
        gap = sp.bbox[0] - cur.bbox[2]

        if same_line and 0.0 <= gap <= _DIM_MERGE_GAP_X:
            cur = _Span(
                f"{cur.text} {sp.text}",
                (
                    min(cur.bbox[0], sp.bbox[0]),
                    min(cur.bbox[1], sp.bbox[1]),
                    max(cur.bbox[2], sp.bbox[2]),
                    max(cur.bbox[3], sp.bbox[3]),
                ),
                max(cur.size, sp.size),
                cur.page_index,
            )
        else:
            out.append(cur)
            cur = sp

    if cur is not None:
        out.append(cur)

    return out


def _detect_dimensions(spans: list[_Span], note_bboxes: set[tuple[float, float, float, float]]) -> list[FAIItem]:
    candidates = [sp for sp in spans if sp.bbox not in note_bboxes]
    candidates = _merge_dim_spans(candidates)

    items: list[FAIItem] = []
    for sp in candidates:
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


def _extract_drawing_bboxes(
    page: fitz.Page,
    pw: float,
    ph: float,
) -> list[tuple[float, float, float, float]]:
    """Collect bounding boxes of vector graphics on ``page``.

    Filters
    -------
    * **Page border:** Any drawing whose bbox has ``width ≥ _PAGE_BORDER_W_FRAC``
      *and* ``height ≥ _PAGE_BORDER_H_FRAC`` of the page is dropped — these are
      usually the outer drawing frame / title-block outline and would mark the
      whole sheet as ``occupied``.
    * **Degenerate paths:** zero-size or sub-pixel paths are skipped.
    * **Thin-line padding:** very thin paths are padded by ``_DRAWING_PADDING``
      so the candidate balloon rectangle intersects visible strokes.

    Returns the filtered, padded bounding boxes.
    """
    boxes: list[tuple[float, float, float, float]] = []

    try:
        drawings = page.get_drawings()
    except Exception:
        return boxes

    for d in drawings:
        rect = d.get("rect")
        if rect is None:
            continue
        try:
            x0, y0, x1, y1 = float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)
        except Exception:
            continue

        if x1 < x0:
            x0, x1 = x1, x0
        if y1 < y0:
            y0, y1 = y1, y0

        w = x1 - x0
        h = y1 - y0
        if w < _DRAWING_MIN_DIM and h < _DRAWING_MIN_DIM:
            continue

        if w >= pw * _PAGE_BORDER_W_FRAC and h >= ph * _PAGE_BORDER_H_FRAC:
            continue

        if w < _DRAWING_PADDING:
            x0 -= _DRAWING_PADDING
            x1 += _DRAWING_PADDING
        if h < _DRAWING_PADDING:
            y0 -= _DRAWING_PADDING
            y1 += _DRAWING_PADDING

        boxes.append((x0, y0, x1, y1))

    return boxes


def _bbox_edge_distance(
    cx: float,
    cy: float,
    bbox: tuple[float, float, float, float],
) -> float:
    """Shortest distance from point (cx, cy) to the closest edge of bbox."""
    bx0, by0, bx1, by1 = bbox
    dx = max(bx0 - cx, 0.0, cx - bx1)
    dy = max(by0 - cy, 0.0, cy - by1)
    return math.hypot(dx, dy)


def _closest_point_on_bbox(
    cx: float,
    cy: float,
    bbox: tuple[float, float, float, float],
) -> tuple[float, float]:
    """Project (cx, cy) onto bbox: clamp coordinates to the bbox extents."""
    bx0, by0, bx1, by1 = bbox
    return (max(bx0, min(bx1, cx)), max(by0, min(by1, cy)))


def _place_balloon_center(
    item_bbox: tuple[float, float, float, float],
    all_text_bboxes: list[tuple[float, float, float, float]],
    placed_centers: list[tuple[float, float]],
    pw: float,
    ph: float,
    all_drawing_bboxes: list[tuple[float, float, float, float]] | None = None,
) -> tuple[float, float, tuple[float, float] | None]:
    """Place a balloon via **grid search** over a padded ``item_bbox`` region.

    Returns ``(cx, cy, leader_anchor)``. A leader anchor is returned when the
    winning balloon centre lies farther than ``CIRCLE_RADIUS *
    _LEADER_DISTANCE_FROM_CENTER_MULT`` from ``(mcx, mcy)`` — then
    :func:`_annotate_pdf` draws a black leader from the balloon rim to the
    nearest point on ``item_bbox``.

    Search region
    -------------
    Grid bounds are the dimension rectangle expanded by ``MAX_DIST =
    CIRCLE_RADIUS * _GRID_EXPAND_FACTOR`` on **each** side::

        [x0 - MAX_DIST, y0 - MAX_DIST, x1 + MAX_DIST, y1 + MAX_DIST]

    clipped to the drawable page. Step size is ``CIRCLE_RADIUS /
    _GRID_STEP_DIVISOR``. Every lattice point is scored; the **global**
    minimum wins.

    Score (lower is better)
    -----------------------
    ::

        score = total_inter * 500
              + drawing_inter * 300
              + (cx-mcx)² + (cy-mcy)²
              + (_EDGE_BAND_BONUS if band_snap else 0)

    ``band_snap`` is true when the balloon centre lies in the dimension's
    vertical extent **or** horizontal extent (``y0≤cy≤y1`` or ``x0≤cx≤x1``),
    encouraging side/top/bottom placement like manual drafting.

    ``drawing_inter`` sums overlap areas with vector path bboxes — heavily
    penalised but never treated as a hard discard so dense drawings still
    yield a least-bad placement.
    """
    x0, y0, x1, y1 = item_bbox
    mcx = (x0 + x1) / 2
    mcy = (y0 + y1) / 2
    eff = CIRCLE_RADIUS + 2.0
    balloon_dist = 2 * CIRCLE_RADIUS + _BALLOON_GAP
    step = CIRCLE_RADIUS / _GRID_STEP_DIVISOR
    max_dist = CIRCLE_RADIUS * _GRID_EXPAND_FACTOR
    leader_trig = CIRCLE_RADIUS * _LEADER_DISTANCE_FROM_CENTER_MULT

    drawings = all_drawing_bboxes or []

    gx0 = max(eff, x0 - max_dist)
    gy0 = max(eff, y0 - max_dist)
    gx1 = min(pw - eff, x1 + max_dist)
    gy1 = min(ph - eff, y1 + max_dist)

    best: tuple[float, float] | None = None
    best_score = float("inf")

    cx = gx0
    while cx <= gx1 + 1e-9:
        cy = gy0
        while cy <= gy1 + 1e-9:
            cb = (cx - eff, cy - eff, cx + eff, cy + eff)

            total_inter = 0.0
            drawing_inter = 0.0

            for tb in all_text_bboxes:
                if _rects_overlap(cb, tb):
                    ix = max(0.0, min(cb[2], tb[2]) - max(cb[0], tb[0]))
                    iy = max(0.0, min(cb[3], tb[3]) - max(cb[1], tb[1]))
                    total_inter += ix * iy

            if _rects_overlap(cb, item_bbox):
                ix = max(0.0, min(cb[2], x1) - max(cb[0], x0))
                iy = max(0.0, min(cb[3], y1) - max(cb[1], y0))
                total_inter += ix * iy

            for px, py in placed_centers:
                if math.hypot(cx - px, cy - py) < balloon_dist:
                    total_inter += balloon_dist * balloon_dist

            for db in drawings:
                if _rects_overlap(cb, db):
                    ix = max(0.0, min(cb[2], db[2]) - max(cb[0], db[0]))
                    iy = max(0.0, min(cb[3], db[3]) - max(cb[1], db[1]))
                    drawing_inter += ix * iy

            dist = (cx - mcx) ** 2 + (cy - mcy) ** 2

            band_snap = (y0 <= cy <= y1) or (x0 <= cx <= x1)
            edge_bonus = _EDGE_BAND_BONUS if band_snap else 0.0

            score = (
                total_inter * _TEXT_OVERLAP_WEIGHT
                + drawing_inter * _DRAWING_OVERLAP_WEIGHT
                + dist
                + edge_bonus
            )
            if score < best_score:
                best_score = score
                best = (cx, cy)

            cy += step
        cx += step

    if best is None:
        best = (max(eff, x1 + CIRCLE_RADIUS + 6.0), max(eff, mcy))

    center_dist = math.hypot(best[0] - mcx, best[1] - mcy)
    leader = (
        _closest_point_on_bbox(best[0], best[1], item_bbox)
        if center_dist > leader_trig
        else None
    )
    return (best[0], best[1], leader)


def _nudge_note_center(
    cx: float,
    cy: float,
    placed: list[tuple[float, float]],
    pw: float,
    ph: float,
) -> tuple[float, float]:
    """Shift a Note balloon vertically until it no longer collides with placed ones."""
    eff = CIRCLE_RADIUS + 2.0
    step = 2 * CIRCLE_RADIUS + _BALLOON_GAP
    balloon_dist = 2 * CIRCLE_RADIUS + _BALLOON_GAP

    for _ in range(40):
        collides = any(math.hypot(cx - px, cy - py) < balloon_dist for px, py in placed)
        if not collides:
            return (cx, cy)
        cy -= step
        cy = max(eff, min(ph - eff, cy))

    return (cx, cy)


def _annotate_pdf(
    doc: fitz.Document,
    items: list[FAIItem],
    page_text_bboxes: list[list[tuple[float, float, float, float]]],
    page_drawing_bboxes: list[list[tuple[float, float, float, float]]] | None = None,
) -> bytes:
    placed_by_page: dict[int, list[tuple[float, float]]] = {}

    for item in items:
        if item.page_index >= len(doc):
            continue
        page = doc[item.page_index]
        pw, ph = page.rect.width, page.rect.height
        bboxes = page_text_bboxes[item.page_index] if item.page_index < len(page_text_bboxes) else []
        drawing_bboxes: list[tuple[float, float, float, float]] = []
        if page_drawing_bboxes is not None and item.page_index < len(page_drawing_bboxes):
            drawing_bboxes = page_drawing_bboxes[item.page_index]
        placed = placed_by_page.setdefault(item.page_index, [])

        leader_anchor: tuple[float, float] | None = None
        if item.dimension_type == "Note":
            cx = item.bbox[0] - _NOTE_BALLOON_OFFSET_X
            cy = (item.bbox[1] + item.bbox[3]) / 2
            eff = CIRCLE_RADIUS + 2.0
            cx = max(eff, min(pw - eff, cx))
            cy = max(eff, min(ph - eff, cy))
            cx, cy = _nudge_note_center(cx, cy, placed, pw, ph)
        else:
            cx, cy, leader_anchor = _place_balloon_center(
                item.bbox, bboxes, placed, pw, ph, drawing_bboxes,
            )

        placed.append((cx, cy))

        if leader_anchor is not None:
            ax, ay = leader_anchor
            dx = ax - cx
            dy = ay - cy
            d = math.hypot(dx, dy)
            if d > CIRCLE_RADIUS + 0.5:
                sx = cx + dx / d * CIRCLE_RADIUS
                sy = cy + dy / d * CIRCLE_RADIUS
                page.draw_line(
                    fitz.Point(sx, sy),
                    fitz.Point(ax, ay),
                    color=_LEADER_LINE_COLOR,
                    width=_LEADER_LINE_WIDTH,
                )

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


def _geometry_lists_from_pdf(
    pdf_path: str | Path,
) -> tuple[
    list[list[tuple[float, float, float, float]]],
    list[list[tuple[float, float, float, float]]],
]:
    """Recompute per-page text and drawing bboxes (same rules as :func:`run_fai`)."""
    pdf_path = Path(pdf_path)
    doc = fitz.open(str(pdf_path))
    try:
        page_text_bboxes: list[list[tuple[float, float, float, float]]] = []
        page_drawing_bboxes: list[list[tuple[float, float, float, float]]] = []
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            pw, ph = page.rect.width, page.rect.height
            raw_spans = _extract_spans(page, page_idx)
            page_text_bboxes.append([sp.bbox for sp in raw_spans])
            all_drawing_bboxes = _extract_drawing_bboxes(page, pw, ph)
            page_drawing_bboxes.append(all_drawing_bboxes)
        return page_text_bboxes, page_drawing_bboxes
    finally:
        doc.close()


def save_debug_pdf(
    pdf_path: str | Path,
    out_path: str | Path,
    page_text_bboxes: list[list[tuple[float, float, float, float]]] | None = None,
    page_drawing_bboxes: list[list[tuple[float, float, float, float]]] | None = None,
) -> None:
    """Write a PDF with **blue** stroke around every text span and **red** around drawings.

    If *page_text_bboxes* / *page_drawing_bboxes* are omitted, they are
    recomputed from *pdf_path* with the same extraction as the FAI pipeline
    (``_extract_spans`` + ``_extract_drawing_bboxes``).
    """
    pdf_path = Path(pdf_path)
    out_path = Path(out_path)
    if page_text_bboxes is None or page_drawing_bboxes is None:
        page_text_bboxes, page_drawing_bboxes = _geometry_lists_from_pdf(pdf_path)

    doc = fitz.open(str(pdf_path))
    try:
        for pi in range(len(doc)):
            page = doc[pi]
            if pi < len(page_text_bboxes):
                for bbox in page_text_bboxes[pi]:
                    x0, y0, x1, y1 = bbox
                    sh = page.new_shape()
                    sh.draw_rect(fitz.Rect(x0, y0, x1, y1))
                    sh.finish(color=_DEBUG_TEXT_STROKE, width=0.35)
                    sh.commit()
            if pi < len(page_drawing_bboxes):
                for bbox in page_drawing_bboxes[pi]:
                    x0, y0, x1, y1 = bbox
                    sh = page.new_shape()
                    sh.draw_rect(fitz.Rect(x0, y0, x1, y1))
                    sh.finish(color=_DEBUG_DRAWING_STROKE, width=0.35)
                    sh.commit()
    finally:
        doc.save(str(out_path))
        doc.close()


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
    page_drawing_bboxes: list[list[tuple[float, float, float, float]]] = []

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        pw, ph = page.rect.width, page.rect.height
        page_sizes.append((pw, ph))

        raw_spans = _extract_spans(page, page_idx)
        page_text_bboxes.append([sp.bbox for sp in raw_spans])
        all_drawing_bboxes = _extract_drawing_bboxes(page, pw, ph)
        page_drawing_bboxes.append(all_drawing_bboxes)
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

    annotated_bytes = _annotate_pdf(
        doc, items, page_text_bboxes, page_drawing_bboxes,
    )
    doc.close()
    return result, annotated_bytes


# ---------------------------------------------------------------------------
# CLI test harness
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    argv = [a for a in sys.argv if a != "--debug"]
    debug = len(argv) != len(sys.argv)

    if len(argv) < 2:
        print("Usage: python fai_parser.py <drawing.pdf> [--debug]")
        sys.exit(1)

    pdf = Path(argv[1])
    if not pdf.exists():
        print(f"File not found: {pdf}")
        sys.exit(1)

    result, annotated = run_fai(pdf)
    out_pdf = pdf.with_name(pdf.stem + "_annotated.pdf")
    out_csv = pdf.with_name(pdf.stem + "_fai.csv")
    out_pdf.write_bytes(annotated)
    out_csv.write_text(items_to_csv(result.items), encoding="utf-8-sig")
    print(f"Wrote {out_pdf} and {out_csv} ({len(result.items)} items)")

    if debug:
        dbg_out = pdf.with_name(pdf.stem + "_geometry_debug.pdf")
        save_debug_pdf(pdf, dbg_out)
        print(f"Wrote {dbg_out} (blue=text spans, red=drawings)")
