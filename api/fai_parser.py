"""
FAI (First Article Inspection) auto-ballooning for vector PDF engineering drawings.

Pipeline (pure PyMuPDF + stdlib, no LLM):
1. Extract text spans from every page.
2. Filter out border grid labels and title-block text.
3. Detect dimensions via regex (radius, diameter, angle, linear + tolerances).
4. Detect numbered notes from the NOTES section.
5. Detect TOLERANCES / UNLESS OTHERWISE SPECIFIED block.
6. Cluster all targets spatially (Euclidean threshold).
7. Sort clusters clockwise (global centroid), then items within each cluster
   clockwise (local centroid) — starting from 12-o'clock.
8. Assign sequential balloon numbers after the combined sort.
9. Place balloons with fixed offsets (left / right fallback); snap notes
   to a single vertical axis.
10. Export a 5-column Hebrew CSV.
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

DimensionType = Literal["Radius", "Diameter", "Angle", "Linear", "Note", "Tolerances"]


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

_TITLE_BLOCK_X_FRAC = 0.62
_TITLE_BLOCK_Y_FRAC = 0.72
_BORDER_MARGIN_FRAC = 0.03

BALLOON_OFFSET = 20.0
PAGE_EDGE_MARGIN = 30.0

# Spatial clustering distance threshold (PDF user-space units ≈ points)
CLUSTER_DIST = 80.0

# Maximum Y gap between consecutive note bullets before we stop collecting
NOTE_BREAK_Y = 60.0


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
_RE_NOTES_HEADER = re.compile(r"^\s*NOTES?\s*[:.\-]?\s*$", re.I)
_RE_NOTE_BULLET = re.compile(r"^\s*(\d+)\s*[.)]\s+")
_RE_BORDER_LABEL = re.compile(r"^[A-Za-z0-9]$")
_RE_THREAD = re.compile(
    r"(?:M\d|#\d|UNC|UNF|UNJC|UNJF|\d+[/-]\d+\s*UN)", re.I
)

_RE_DIM_HINT = re.compile(
    r"("
    r"\d+[\d.,]*\s*[±+\-]|"
    r"[⌀Øø]|\bR\s*\d|\bR\.|"
    r"\d+\s*°|°\s*\d+|"
    r"#[\d\-]+|M\d|UNC|UNF|UNJC|THREAD|"
    r"\bRa\b|RZ|"
    r"TYP\.?|REF\.?|MAX\.?|MIN\.?|"
    r"\d+[\d.,]*\s*[xX]\s*\d+|"
    r"\d+[\d.,]{1,}\b"
    r")",
    re.I,
)

_RE_TOLERANCES = re.compile(
    r"\b(TOLERANCES?|UNLESS\s+OTHERWISE\s+SPECIFIED)\b",
    re.I,
)


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


def _filter_spans(
    spans: list[_Span], pw: float, ph: float,
) -> list[_Span]:
    return [
        sp for sp in spans
        if not _is_border_label(sp, pw, ph) and not _is_in_title_block(sp, pw, ph)
    ]


# ---------------------------------------------------------------------------
# NOTES parser
# ---------------------------------------------------------------------------

def _parse_notes(spans: list[_Span], page_index: int) -> list[FAIItem]:
    """Find the NOTES header on the given page and collect numbered bullets."""
    header_bbox: tuple[float, float, float, float] | None = None
    for sp in spans:
        if sp.page_index == page_index and _RE_NOTES_HEADER.match(sp.text):
            header_bbox = sp.bbox
            break
    if header_bbox is None:
        return []

    page_spans = sorted(
        [sp for sp in spans if sp.page_index == page_index],
        key=lambda s: (s.bbox[1], s.bbox[0]),
    )

    notes: list[FAIItem] = []
    prev_y1 = header_bbox[3]

    for sp in page_spans:
        if sp.bbox[1] < header_bbox[3]:
            continue
        if sp.bbox[1] - prev_y1 > NOTE_BREAK_Y:
            break
        m = _RE_NOTE_BULLET.match(sp.text)
        if m:
            notes.append(FAIItem(
                text=sp.text.strip(),
                dimension_type="Note",
                tolerance="",
                page_index=page_index,
                bbox=sp.bbox,
            ))
            prev_y1 = sp.bbox[3]

    return notes


# ---------------------------------------------------------------------------
# TOLERANCES parser
# ---------------------------------------------------------------------------

def _parse_tolerances(spans: list[_Span], page_index: int) -> list[FAIItem]:
    """Find a TOLERANCES / UNLESS OTHERWISE SPECIFIED block on the page."""
    matched: list[_Span] = []
    for sp in spans:
        if sp.page_index == page_index and _RE_TOLERANCES.search(sp.text):
            matched.append(sp)

    if not matched:
        return []

    x0 = min(sp.bbox[0] for sp in matched)
    y0 = min(sp.bbox[1] for sp in matched)
    x1 = max(sp.bbox[2] for sp in matched)
    y1 = max(sp.bbox[3] for sp in matched)

    return [FAIItem(
        text="TOLERANCES",
        dimension_type="Tolerances",
        tolerance="",
        page_index=page_index,
        bbox=(x0, y0, x1, y1),
    )]


# ---------------------------------------------------------------------------
# Dimension detection & classification
# ---------------------------------------------------------------------------

def _extract_tolerance(text: str) -> tuple[str, str]:
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


def _detect_dimensions(
    spans: list[_Span],
    exclude_bboxes: set[tuple[float, float, float, float]],
) -> list[FAIItem]:
    items: list[FAIItem] = []
    for sp in spans:
        if sp.bbox in exclude_bboxes:
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
# Geometry helpers
# ---------------------------------------------------------------------------

def _centroid(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    return ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)


def _euclid(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _clockwise_angle(cx: float, cy: float, x: float, y: float) -> float:
    """Angle from 12-o'clock, increasing clockwise (0 .. 2*pi)."""
    a = math.atan2(x - cx, -(y - cy))
    return a + 2 * math.pi if a < 0 else a


def _bbox_union(items: list[FAIItem]) -> tuple[float, float, float, float]:
    x0 = min(it.bbox[0] for it in items)
    y0 = min(it.bbox[1] for it in items)
    x1 = max(it.bbox[2] for it in items)
    y1 = max(it.bbox[3] for it in items)
    return (x0, y0, x1, y1)


# ---------------------------------------------------------------------------
# Spatial clustering
# ---------------------------------------------------------------------------

def _cluster(targets: list[FAIItem]) -> list[list[FAIItem]]:
    """Single-linkage clustering by Euclidean distance on bbox centroids."""
    clusters: list[list[FAIItem]] = []
    for t in targets:
        c = _centroid(t.bbox)
        joined = False
        for cl in clusters:
            if any(_euclid(c, _centroid(x.bbox)) <= CLUSTER_DIST for x in cl):
                cl.append(t)
                joined = True
                break
        if not joined:
            clusters.append([t])
    return clusters


# ---------------------------------------------------------------------------
# Clockwise sort (global clusters then local items)
# ---------------------------------------------------------------------------

def _sort_clockwise(items: list[FAIItem], cx: float, cy: float) -> list[FAIItem]:
    return sorted(items, key=lambda it: _clockwise_angle(cx, cy, *_centroid(it.bbox)))


def _assign_numbers(
    all_targets: list[FAIItem],
    page_sizes: list[tuple[float, float]],
) -> list[FAIItem]:
    """Cluster, sort clockwise globally then locally, assign sequential numbers."""
    pages: dict[int, list[FAIItem]] = {}
    for t in all_targets:
        pages.setdefault(t.page_index, []).append(t)

    ordered: list[FAIItem] = []
    for pi in sorted(pages):
        targets = pages[pi]
        clusters = _cluster(targets)

        cluster_centroids = []
        for cl in clusters:
            xs = [_centroid(it.bbox)[0] for it in cl]
            ys = [_centroid(it.bbox)[1] for it in cl]
            cluster_centroids.append((sum(xs) / len(xs), sum(ys) / len(ys)))

        gcx = sum(c[0] for c in cluster_centroids) / len(cluster_centroids)
        gcy = sum(c[1] for c in cluster_centroids) / len(cluster_centroids)

        indexed = list(range(len(clusters)))
        indexed.sort(key=lambda i: _clockwise_angle(gcx, gcy, *cluster_centroids[i]))

        for i in indexed:
            cl = clusters[i]
            lcx, lcy = cluster_centroids[i]
            ordered.extend(_sort_clockwise(cl, lcx, lcy))

    for i, item in enumerate(ordered, start=1):
        item.balloon_number = i

    return ordered


# ---------------------------------------------------------------------------
# Balloon annotation — deterministic fixed-offset placement
# ---------------------------------------------------------------------------

def _rects_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def _balloon_center_offset(
    item: FAIItem,
    pw: float,
    _ph: float,
) -> tuple[float, float]:
    """Fixed-offset balloon placement: left of box, fallback right near page edge."""
    bx0, by0, _bx1, by1 = item.bbox
    mid_y = (by0 + by1) / 2

    cx = bx0 - BALLOON_OFFSET
    if cx < PAGE_EDGE_MARGIN:
        cx = item.bbox[2] + BALLOON_OFFSET
    if cx > pw - PAGE_EDGE_MARGIN:
        cx = max(PAGE_EDGE_MARGIN, bx0 - BALLOON_OFFSET)

    return (cx, mid_y)


def _compute_note_grid_positions(
    notes: list[FAIItem],
) -> dict[int, tuple[float, float]]:
    """Snap all Note balloons to one vertical axis per page."""
    pages: dict[int, list[FAIItem]] = {}
    for n in notes:
        pages.setdefault(n.page_index, []).append(n)

    positions: dict[int, tuple[float, float]] = {}
    for _pi, page_notes in pages.items():
        axis_x = min(n.bbox[0] for n in page_notes) - BALLOON_OFFSET
        axis_x = max(PAGE_EDGE_MARGIN, axis_x)
        for n in page_notes:
            mid_y = (n.bbox[1] + n.bbox[3]) / 2
            positions[n.balloon_number] = (axis_x, mid_y)
    return positions


def _annotate_pdf(
    doc: fitz.Document,
    items: list[FAIItem],
    page_text_bboxes: list[list[tuple[float, float, float, float]]],
) -> bytes:
    note_grid = _compute_note_grid_positions(
        [it for it in items if it.dimension_type == "Note"]
    )

    for item in items:
        if item.page_index >= len(doc):
            continue
        page = doc[item.page_index]
        pw, ph = page.rect.width, page.rect.height

        if item.balloon_number in note_grid:
            cx, cy = note_grid[item.balloon_number]
        else:
            cx, cy = _balloon_center_offset(item, pw, ph)

        eff = CIRCLE_RADIUS + 2.0
        cx = max(eff, min(pw - eff, cx))
        cy = max(eff, min(ph - eff, cy))

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
    all_targets: list[FAIItem] = []
    page_text_bboxes: list[list[tuple[float, float, float, float]]] = []

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        pw, ph = page.rect.width, page.rect.height
        page_sizes.append((pw, ph))

        raw_spans = _extract_spans(page, page_idx)
        page_text_bboxes.append([sp.bbox for sp in raw_spans])
        spans = _filter_spans(raw_spans, pw, ph)

        notes = _parse_notes(spans, page_idx)
        tolerances = _parse_tolerances(spans, page_idx)

        exclude_bboxes = {n.bbox for n in notes} | {t.bbox for t in tolerances}
        dims = _detect_dimensions(spans, exclude_bboxes)

        all_targets.extend(notes)
        all_targets.extend(tolerances)
        all_targets.extend(dims)

    items = _assign_numbers(all_targets, page_sizes)
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
