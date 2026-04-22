"""
Engineering-drawing dimension extractor (clean CAD PDFs).

Pipeline:
1. Classify each page internally: vector text vs scan (no user-facing modes).
2. Build dimension candidates from PyMuPDF lines (title block excluded) and
   optionally merge GPT-4o Vision candidates (IoU dedupe) when vector yield is low.
3. Thin text LLM: order + type + merge candidate ids into final rows.
4. Annotate PDF using label placement that avoids overlapping dimension text bboxes.

Offline calibration (optional): compare paired PDFs (clean vs hand-stamped) to
measure (dx, dy) from dimension text to human balloon centers, then tune
placement direction order / margins in place_label_circle_center.
"""

from __future__ import annotations

import base64
import io
import json
import re
from pathlib import Path

import fitz  # PyMuPDF
from openai import OpenAI
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Types & schema
# ---------------------------------------------------------------------------

DIMENSION_TYPES: list[str] = [
    "אורך",
    "רוחב",
    "גובה",
    "עומק",
    "עובי",
    "קוטר (⌀)",
    "רדיוס (R)",
    "היקף",
    "פסיעה (Pitch)",
    "קוטר פנימי (ID)",
    "קוטר חיצוני (OD)",
    "זווית",
    "שיפוע (Taper)",
    "פאזה (Chamfer)",
    "רדיוס פינה (Fillet)",
    "מרחק בין מרכזים (C-to-C)",
    "טולרנס (Tolerance)",
    "טיב שטח (Ra)",
    "ניצבות",
    "מקביליות",
    "ריכוזיות",
    "מידת הברגה",
    "משקל יחידה",
    "נפח",
    "צפיפות",
    "קנה מידה (Scale)",
    "הערה (Note)",
]

# Title block exclusion (bottom-right), as fraction of page width/height.
_TITLE_BLOCK_X0_FRAC = 0.62
_TITLE_BLOCK_Y0_FRAC = 0.74
_MERGE_VISION_IF_VECTOR_FEWER_THAN = 14
_VISION_IOU_DEDUPE_THRESHOLD = 0.38


class DimensionItem(BaseModel):
    number: int = Field(description="מספר סידורי לפי כיוון השעון, מתחיל מ-1")
    dimension_type: str = Field(
        description=(
            "סוג המידה – חייב להיות אחד מהרשימה הבאה בדיוק: "
            + ", ".join(DIMENSION_TYPES)
        )
    )
    value: str = Field(
        description=(
            "ערך המידה בדיוק כפי שמופיע בשרטוט, כולל טולרנסים אם קיימים."
        )
    )
    x_pct: float = Field(
        description="מיקום X מרכז bbox כאחוז מרוחב העמוד (0–1)"
    )
    y_pct: float = Field(
        description="מיקום Y מרכז bbox כאחוז מגובה העמוד (0–1)"
    )
    bbox_x0: float | None = Field(default=None, description="PDF user space")
    bbox_y0: float | None = Field(default=None)
    bbox_x1: float | None = Field(default=None)
    bbox_y1: float | None = Field(default=None)


class DrawingPage(BaseModel):
    dimensions: list[DimensionItem] = Field(
        description="רשימת כל המידות וההערות שזוהו בעמוד זה"
    )


class DrawingAnalysis(BaseModel):
    drawing_title: str = Field(description="שם החלק / כותרת השרטוט")
    part_number: str = Field(description="מספר חלק (Part Number / DWG Number)")
    pages: list[DrawingPage] = Field(description="ניתוח לכל עמוד בשרטוט")
    page_routes: list[str] = Field(
        default_factory=list,
        description="Internal per-page route tag (debug): vector_only, vector+vision, scan, scan_fallback",
    )


class DrawingCandidate(BaseModel):
    """One spatial text region that may become a dimension row."""

    candidate_id: int
    page_index: int
    text: str
    x0: float
    y0: float
    x1: float
    y1: float


class VisionCandidate(BaseModel):
    candidate_id: int
    raw_text: str
    x0_pct: float = Field(ge=0.0, le=1.0)
    y0_pct: float = Field(ge=0.0, le=1.0)
    x1_pct: float = Field(ge=0.0, le=1.0)
    y1_pct: float = Field(ge=0.0, le=1.0)


class VisionCandidatePage(BaseModel):
    candidates: list[VisionCandidate]


class ClassifiedDimensionRow(BaseModel):
    sequence_number: int
    dimension_type: str
    value: str
    source_candidate_ids: list[int] = Field(
        description="Ids from the input candidate list; merge multiple into one row if needed"
    )


class ClassifiedPageResult(BaseModel):
    dimensions: list[ClassifiedDimensionRow]


class _TitleInfo(BaseModel):
    drawing_title: str = Field(description="Drawing title from the title block")
    part_number: str = Field(description="Part number / DWG number from the title block")


# ---------------------------------------------------------------------------
# Regex / heuristics
# ---------------------------------------------------------------------------

_DIM_LINE_HINT = re.compile(
    r"("
    r"\d+[\d.,]*\s*[±\+\-]|"  # tolerance style
    r"[⌀Øø]|\bR\d|R\.|"
    r"\d+\s*°|°\s*\d+|"
    r"#[\d\-]+|M\d|UNC|UNF|UNJC|THREAD|"
    r"\bRa\b|RZ|"
    r"TYP\.?|REF\.?|MAX\.?|MIN\.?|"
    r"\d+[\d.,]*\s*x\s*\d+|"  # e.g. 0.3x45
    r"\d+[\d.,]{1,}\b"  # plain number with optional decimals
    r")",
    re.I,
)

_NOTE_HINT = re.compile(
    r"^\s*(\d+[\.)])\s+|NOTE|NOTES|הערה|כללי|GENERAL|MATERIAL|SURFACE|FINISH|HEAT|TREAT",
    re.I,
)


def _line_looks_dimension_like(text: str) -> bool:
    """High-precision filter: avoid title-block noise from 'any line with a digit'."""
    t = text.strip()
    if len(t) < 1:
        return False
    if _NOTE_HINT.search(t):
        return True
    if _DIM_LINE_HINT.search(t):
        return True
    if len(t) <= 22 and re.search(r"\d", t):
        if re.search(r"[⌀Øø°±\d\.\#RMABCXYZ]", t, re.I):
            return True
    return False


def _bbox_center_in_title_block(
    x0: float, y0: float, x1: float, y1: float, pw: float, ph: float
) -> bool:
    cx = (x0 + x1) / 2
    cy = (y0 + y1) / 2
    return cx >= pw * _TITLE_BLOCK_X0_FRAC and cy >= ph * _TITLE_BLOCK_Y0_FRAC


def _block_area(bbox: tuple[float, float, float, float]) -> float:
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


def classify_page_route(page: fitz.Page) -> str:
    """Return 'vector' or 'scan' for internal candidate extraction."""
    d = page.get_text("dict")
    blocks = d.get("blocks", [])
    text = page.get_text("text") or ""
    text_len = len(text.strip())
    span_count = 0
    dim_like = 0
    img_area = 0.0
    text_area = 0.0
    for block in blocks:
        if block.get("type") == 0:
            for line in block.get("lines", []):
                parts: list[str] = []
                for span in line.get("spans", []):
                    st = span.get("text", "").strip()
                    if st:
                        span_count += 1
                        parts.append(st)
                    bb = span.get("bbox")
                    if bb:
                        text_area += _block_area(bb)
                line_txt = " ".join(parts).strip()
                if line_txt and _line_looks_dimension_like(line_txt):
                    dim_like += 1
        elif block.get("type") == 1:
            bb = block.get("bbox")
            if bb:
                img_area += _block_area(bb)
    total_media = img_area + text_area
    image_ratio = img_area / total_media if total_media > 0 else 0.0

    if dim_like >= 10 or (dim_like >= 4 and text_len >= 150):
        return "vector"
    if text_len < 60 and image_ratio > 0.55:
        return "scan"
    if span_count >= 30 and dim_like >= 2:
        return "vector"
    if text_len >= 100 and dim_like >= 1:
        return "vector"
    return "scan"


def page_text_and_image_ratio(page: fitz.Page) -> tuple[int, float]:
    """Strip length and approximate image area ratio for merge heuristics."""
    d = page.get_text("dict")
    text = (page.get_text("text") or "").strip()
    img_area = 0.0
    text_area = 0.0
    for block in d.get("blocks", []):
        if block.get("type") == 1:
            bb = block.get("bbox")
            if bb:
                img_area += _block_area(bb)
        elif block.get("type") == 0:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    bb = span.get("bbox")
                    if bb:
                        text_area += _block_area(bb)
    total = img_area + text_area
    ratio = img_area / total if total > 0 else 0.0
    return len(text), ratio


# ---------------------------------------------------------------------------
# PDF → image
# ---------------------------------------------------------------------------


def pdf_page_to_image(pdf_path: str | Path, page_num: int = 0, dpi: int = 200) -> bytes:
    doc = fitz.open(str(pdf_path))
    page = doc[page_num]
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img_bytes = pix.tobytes("png")
    doc.close()
    return img_bytes


def get_page_count(pdf_path: str | Path) -> int:
    doc = fitz.open(str(pdf_path))
    count = len(doc)
    doc.close()
    return count


def _image_to_data_url(img_bytes: bytes) -> str:
    b64 = base64.b64encode(img_bytes).decode()
    return f"data:image/png;base64,{b64}"


# ---------------------------------------------------------------------------
# Vector candidate extraction (merged lines)
# ---------------------------------------------------------------------------


def extract_dimension_candidates_vector(
    pdf_path: str | Path,
    page_index: int,
    start_id: int = 1,
) -> list[DrawingCandidate]:
    doc = fitz.open(str(pdf_path))
    page = doc[page_index]
    pw, ph = page.rect.width, page.rect.height
    out: list[DrawingCandidate] = []
    cid = start_id
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue
            texts: list[str] = []
            x0 = y0 = float("inf")
            x1 = y1 = float("-inf")
            for span in spans:
                t = span.get("text", "").strip()
                if not t:
                    continue
                texts.append(t)
                b = span["bbox"]
                x0 = min(x0, b[0])
                y0 = min(y0, b[1])
                x1 = max(x1, b[2])
                y1 = max(y1, b[3])
            if x0 == float("inf"):
                continue
            if _bbox_center_in_title_block(x0, y0, x1, y1, pw, ph):
                continue
            line_text = " ".join(texts).strip()
            if not line_text or not _line_looks_dimension_like(line_text):
                continue
            out.append(
                DrawingCandidate(
                    candidate_id=cid,
                    page_index=page_index,
                    text=line_text,
                    x0=x0,
                    y0=y0,
                    x1=x1,
                    y1=y1,
                )
            )
            cid += 1
    doc.close()
    return out


def _vision_candidates_to_drawing_candidates(
    vc: VisionCandidatePage,
    page_index: int,
    pw: float,
    ph: float,
) -> list[DrawingCandidate]:
    out: list[DrawingCandidate] = []
    for i, c in enumerate(vc.candidates, start=1):
        x0 = min(c.x0_pct, c.x1_pct) * pw
        x1 = max(c.x0_pct, c.x1_pct) * pw
        y0 = min(c.y0_pct, c.y1_pct) * ph
        y1 = max(c.y0_pct, c.y1_pct) * ph
        out.append(
            DrawingCandidate(
                candidate_id=i,
                page_index=page_index,
                text=c.raw_text.strip(),
                x0=x0,
                y0=y0,
                x1=x1,
                y1=y1,
            )
        )
    return out


def _iou_box(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    aa = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    bb = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    union = aa + bb - inter
    return inter / union if union > 0 else 0.0


def _renumber_candidates(
    cands: list[DrawingCandidate], page_index: int
) -> list[DrawingCandidate]:
    return [
        DrawingCandidate(
            candidate_id=i,
            page_index=page_index,
            text=c.text,
            x0=c.x0,
            y0=c.y0,
            x1=c.x1,
            y1=c.y1,
        )
        for i, c in enumerate(cands, start=1)
    ]


def merge_vector_and_vision_candidates(
    primary: list[DrawingCandidate],
    secondary: list[DrawingCandidate],
    page_index: int,
    iou_threshold: float = _VISION_IOU_DEDUPE_THRESHOLD,
) -> list[DrawingCandidate]:
    """Keep all primary candidates; add vision boxes that do not overlap strongly."""
    merged: list[DrawingCandidate] = list(primary)
    for c in secondary:
        box = (c.x0, c.y0, c.x1, c.y1)
        if any(
            _iou_box(box, (m.x0, m.y0, m.x1, m.y1)) >= iou_threshold
            for m in merged
        ):
            continue
        merged.append(
            DrawingCandidate(
                candidate_id=0,
                page_index=page_index,
                text=c.text.strip(),
                x0=c.x0,
                y0=c.y0,
                x1=c.x1,
                y1=c.y1,
            )
        )
    return _renumber_candidates(merged, page_index)


VISION_CANDIDATES_PROMPT = """\
You extract **candidate regions** from an engineering drawing page image.
Each candidate is one piece of text: a dimension value, tolerance, GD&T callout, \
thread spec, or one NOTES bullet line.

## Rules
- Return a flat list with local ids 1,2,3,... (candidate_id).
- raw_text: copy text exactly as read from the drawing.
- Bounding box in **normalized page coordinates** (0.0–1.0): \
x0_pct,y0_pct is top-left of the text box, x1_pct,y1_pct is bottom-right.
- Include NOTES section lines as separate candidates (usually top-left).
- Merge split dimension text on the same line into **one** candidate when they \
clearly belong together (e.g. "59.0" and "±0.05" adjacent).
- Be exhaustive: include every visible dimension value, note line, GD&T frame, \
and thread callout worth tabulating.

Do **not** assign final dimension numbering — only spatial candidates.
"""


def extract_candidates_via_vision(
    img_bytes: bytes,
    page_index: int,
) -> VisionCandidatePage:
    client = OpenAI()
    user_content: list[dict] = [
        {
            "type": "text",
            "text": (
                f"Page index (for context only): {page_index}. "
                "List all dimension/note text candidates with bounding boxes."
            ),
        },
        {
            "type": "image_url",
            "image_url": {"url": _image_to_data_url(img_bytes), "detail": "high"},
        },
    ]
    completion = client.beta.chat.completions.parse(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": VISION_CANDIDATES_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format=VisionCandidatePage,
        max_tokens=16000,
    )
    result = completion.choices[0].message.parsed
    if result is None:
        raise RuntimeError("Vision candidate extraction failed.")
    return result


# ---------------------------------------------------------------------------
# Thin LLM: order + classify from candidate JSON
# ---------------------------------------------------------------------------

ORDER_CLASSIFY_SYSTEM = """\
You are an expert mechanical drawing analyst. You receive a JSON list of \
**candidates** from one PDF page. Each has: candidate_id, text, cx_pct, cy_pct \
(center of the text box as fraction of page width/height, 0=left/top).

## Your job
Produce the final dimension list for this page:
- sequence_number: 1,2,3,... with no gaps.
- dimension_type: EXACTLY one of these Hebrew labels:
""" + "\n".join(DIMENSION_TYPES) + """

## NUMBERING (same as product rules)
1. Start from **NOTES** (usually top-left): each note bullet = separate item, \
in reading order.
2. Then continue **clockwise** around drawing views from top-left of the sheet.
3. value: must be composed from the candidate text(s) you link — copy faithfully, \
you may merge adjacent candidate lines that are one logical dimension.

## source_candidate_ids
- Every output row must reference at least one candidate_id from the input.
- If one logical dimension was split into two candidates, use both ids.

## COVERAGE (critical)
- Every candidate_id in the input must appear in **exactly one** output row's \
source_candidate_ids (merge duplicates only when two candidates are clearly \
the same text in the same place).
- Do **not** drop candidates because they look like "decorative" sheet text \
unless they are clearly a title, company logo string, or scale bar label only.
- If unsure between duplicate and distinct, prefer keeping both rows.

## Constraints
- Do not invent candidate_ids.
- For ambiguous type, pick the closest from the list.
"""


def order_and_classify_candidates(
    page_index: int,
    candidates: list[DrawingCandidate],
    page_width: float,
    page_height: float,
) -> ClassifiedPageResult:
    if not candidates:
        return ClassifiedPageResult(dimensions=[])

    payload = []
    for c in candidates:
        cx = (c.x0 + c.x1) / 2 / page_width if page_width else 0.0
        cy = (c.y0 + c.y1) / 2 / page_height if page_height else 0.0
        payload.append({
            "candidate_id": c.candidate_id,
            "text": c.text,
            "cx_pct": round(cx, 4),
            "cy_pct": round(cy, 4),
        })

    client = OpenAI()
    completion = client.beta.chat.completions.parse(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": ORDER_CLASSIFY_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Page index: {page_index}\n\n"
                    f"CANDIDATES_JSON:\n{json.dumps(payload, ensure_ascii=False)}"
                ),
            },
        ],
        response_format=ClassifiedPageResult,
        max_tokens=16000,
    )
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise RuntimeError("Order/classify LLM returned no parsed result.")
    return parsed


def _union_bbox(cands: list[DrawingCandidate]) -> tuple[float, float, float, float]:
    x0 = min(c.x0 for c in cands)
    y0 = min(c.y0 for c in cands)
    x1 = max(c.x1 for c in cands)
    y1 = max(c.y1 for c in cands)
    return x0, y0, x1, y1


def _build_dimension_items(
    classified: ClassifiedPageResult,
    candidates: list[DrawingCandidate],
    page_width: float,
    page_height: float,
) -> list[DimensionItem]:
    by_id = {c.candidate_id: c for c in candidates}
    out: list[DimensionItem] = []
    for row in classified.dimensions:
        src = [by_id[i] for i in row.source_candidate_ids if i in by_id]
        if not src:
            continue
        x0, y0, x1, y1 = _union_bbox(src)
        cx = (x0 + x1) / 2
        cy = (y0 + y1) / 2
        out.append(
            DimensionItem(
                number=row.sequence_number,
                dimension_type=row.dimension_type,
                value=row.value,
                x_pct=cx / page_width if page_width else 0.0,
                y_pct=cy / page_height if page_height else 0.0,
                bbox_x0=x0,
                bbox_y0=y0,
                bbox_x1=x1,
                bbox_y1=y1,
            )
        )
    out.sort(key=lambda d: d.number)
    return out


def _fetch_title_block(pdf_path: str | Path) -> _TitleInfo:
    client = OpenAI()
    first_page_img = pdf_page_to_image(pdf_path, page_num=0, dpi=150)
    title_completion = client.beta.chat.completions.parse(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": (
                    "Extract ONLY the drawing title and part number from this "
                    "engineering drawing. Look in the title block (usually "
                    "bottom-right corner)."
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is the title and part number?"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": _image_to_data_url(first_page_img),
                            "detail": "low",
                        },
                    },
                ],
            },
        ],
        response_format=_TitleInfo,
    )
    title_info = title_completion.choices[0].message.parsed
    if title_info is None:
        return _TitleInfo(drawing_title="Unknown", part_number="Unknown")
    return title_info


def analyze_full_drawing(pdf_path: str | Path) -> DrawingAnalysis:
    """Hybrid pipeline: vector candidates, optional vision merge, thin LLM, bbox output."""
    pdf_path = Path(pdf_path)
    doc = fitz.open(str(pdf_path))
    num_pages = len(doc)
    all_pages: list[DrawingPage] = []
    routes_log: list[str] = []
    seq = 1

    for page_idx in range(num_pages):
        page = doc[page_idx]
        pw, ph = page.rect.width, page.rect.height
        route = classify_page_route(page)
        text_len, image_ratio = page_text_and_image_ratio(page)

        vec = extract_dimension_candidates_vector(pdf_path, page_idx, start_id=1)
        candidates: list[DrawingCandidate]
        route_used: str

        if route == "scan" or not vec:
            img_bytes = pdf_page_to_image(pdf_path, page_num=page_idx, dpi=200)
            vpage = extract_candidates_via_vision(img_bytes, page_idx)
            raw = _vision_candidates_to_drawing_candidates(vpage, page_idx, pw, ph)
            candidates = _renumber_candidates(raw, page_idx)
            route_used = "scan" if route == "scan" else "scan_fallback"
        else:
            need_vision_merge = (
                len(vec) < _MERGE_VISION_IF_VECTOR_FEWER_THAN
                or (text_len < 220 and image_ratio > 0.11)
            )
            if need_vision_merge:
                img_bytes = pdf_page_to_image(pdf_path, page_num=page_idx, dpi=200)
                vpage = extract_candidates_via_vision(img_bytes, page_idx)
                vis = _vision_candidates_to_drawing_candidates(
                    vpage, page_idx, pw, ph
                )
                candidates = merge_vector_and_vision_candidates(
                    vec, vis, page_idx
                )
                route_used = "vector+vision"
            else:
                candidates = _renumber_candidates(vec, page_idx)
                route_used = "vector_only"

        classified = order_and_classify_candidates(
            page_idx, candidates, pw, ph
        )
        dims = _build_dimension_items(classified, candidates, pw, ph)
        for d in dims:
            d.number = seq
            seq += 1
        all_pages.append(DrawingPage(dimensions=dims))
        routes_log.append(route_used)

    doc.close()

    title_info = _fetch_title_block(pdf_path)
    return DrawingAnalysis(
        drawing_title=title_info.drawing_title,
        part_number=title_info.part_number,
        pages=all_pages,
        page_routes=routes_log,
    )


# ---------------------------------------------------------------------------
# Legacy span match (fallback annotation)
# ---------------------------------------------------------------------------

def extract_text_spans(pdf_path: str | Path, page_num: int = 0) -> list[dict]:
    doc = fitz.open(str(pdf_path))
    page = doc[page_num]
    spans: list[dict] = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                txt = span["text"].strip()
                if txt:
                    spans.append({
                        "text": txt,
                        "x0": span["bbox"][0],
                        "y0": span["bbox"][1],
                        "x1": span["bbox"][2],
                        "y1": span["bbox"][3],
                    })
    doc.close()
    return spans


_NUM_RE = re.compile(r"[\d]+\.?[\d]*")


def _extract_tokens(value: str) -> list[str]:
    cleaned = value.replace("⌀", "").replace("±", " ").replace("°", " ")
    nums = _NUM_RE.findall(cleaned)
    words = [w for w in re.split(r"[\s,;]+", cleaned) if len(w) >= 3]
    seen: set[str] = set()
    unique: list[str] = []
    for t in nums + words:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


def find_span_for_value(
    value: str,
    spans: list[dict],
    fallback_x_pct: float,
    fallback_y_pct: float,
    page_w: float,
    page_h: float,
) -> tuple[float, float]:
    if not spans:
        return fallback_x_pct * page_w, fallback_y_pct * page_h
    tokens = _extract_tokens(value)
    if not tokens:
        return fallback_x_pct * page_w, fallback_y_pct * page_h
    approx_x = fallback_x_pct * page_w
    approx_y = fallback_y_pct * page_h
    best_span = None
    best_dist = float("inf")
    for token in tokens:
        for sp in spans:
            if token in sp["text"]:
                mid_x = (sp["x0"] + sp["x1"]) / 2
                mid_y = (sp["y0"] + sp["y1"]) / 2
                dist = (mid_x - approx_x) ** 2 + (mid_y - approx_y) ** 2
                if dist < best_dist:
                    best_dist = dist
                    best_span = sp
    if best_span is None:
        return approx_x, approx_y
    return best_span["x0"], (best_span["y0"] + best_span["y1"]) / 2


# ---------------------------------------------------------------------------
# PDF annotation (bbox-first)
# ---------------------------------------------------------------------------

_CIRCLE_RADIUS = 10
_FONT_SIZE = 7
_LABEL_COLOR = (1, 0, 0)
_CIRCLE_FILL = (1, 1, 1)
_CIRCLE_BORDER = (1, 0, 0)
_LABEL_MARGIN = 4.0


def _rects_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return not (ax1 < bx0 or bx1 < ax0 or ay1 < by0 or by1 < ay0)


def _intersection_area(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    return max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)


def place_label_circle_center(
    text_bbox: tuple[float, float, float, float],
    pw: float,
    ph: float,
    circle_radius: float,
    margin: float,
) -> tuple[float, float]:
    """Pick circle center so the circle (plus small padding) does not cover dimension text."""
    x0, y0, x1, y1 = text_bbox
    midx = (x0 + x1) / 2
    midy = (y0 + y1) / 2
    r = circle_radius
    m = margin
    pad = 2.5
    eff = r + pad
    tb = (x0 - 0.5, y0 - 0.5, x1 + 0.5, y1 + 0.5)

    def circle_bbox(cx: float, cy: float) -> tuple[float, float, float, float]:
        cx = max(r, min(pw - r, cx))
        cy = max(r, min(ph - r, cy))
        return (cx - eff, cy - eff, cx + eff, cy + eff)

    trials = [
        (x0 - m - r, midy),
        (midx, y0 - m - r),
        (midx, y1 + m + r),
        (x1 + m + r, midy),
        (x0 - m - r, y0 - m - r),
        (x1 + m + r, y0 - m - r),
        (x0 - m - r, y1 + m + r),
        (x1 + m + r, y1 + m + r),
    ]

    best: tuple[float, float] | None = None
    best_score = float("inf")
    for tcx, tcy in trials:
        cx = max(r, min(pw - r, tcx))
        cy = max(r, min(ph - r, tcy))
        cb = circle_bbox(cx, cy)
        if not _rects_overlap(cb, tb):
            return cx, cy
        inter = _intersection_area(cb, tb)
        dist = (cx - midx) ** 2 + (cy - midy) ** 2
        score = inter * 500.0 + dist
        if score < best_score:
            best_score = score
            best = (cx, cy)
    return best if best is not None else (max(r, x0 - m - r), max(r, midy))


def annotate_pdf(pdf_path: str | Path, analysis: DrawingAnalysis) -> bytes:
    """Draw numbered circles beside dimension text without obscuring the value bbox."""
    doc = fitz.open(str(pdf_path))

    for page_idx, page_analysis in enumerate(analysis.pages):
        if page_idx >= len(doc):
            break
        page = doc[page_idx]
        rect = page.rect
        pw, ph = rect.width, rect.height
        spans = extract_text_spans(pdf_path, page_num=page_idx)

        for dim in page_analysis.dimensions:
            if (
                dim.bbox_x0 is not None
                and dim.bbox_y0 is not None
                and dim.bbox_x1 is not None
                and dim.bbox_y1 is not None
            ):
                tb = (dim.bbox_x0, dim.bbox_y0, dim.bbox_x1, dim.bbox_y1)
            else:
                ax, ay = find_span_for_value(
                    dim.value,
                    spans,
                    dim.x_pct,
                    dim.y_pct,
                    pw,
                    ph,
                )
                tb = (ax, ay - 4, ax + 2, ay + 4)

            cx, cy = place_label_circle_center(
                tb, pw, ph, _CIRCLE_RADIUS, _LABEL_MARGIN
            )

            shape = page.new_shape()
            shape.draw_circle(fitz.Point(cx, cy), _CIRCLE_RADIUS)
            shape.finish(color=_CIRCLE_BORDER, fill=_CIRCLE_FILL, width=0.8)
            shape.commit()

            label = str(dim.number)
            text_point = fitz.Point(
                cx - len(label) * (_FONT_SIZE * 0.3),
                cy + _FONT_SIZE * 0.35,
            )
            page.insert_text(
                text_point,
                label,
                fontsize=_FONT_SIZE,
                color=_LABEL_COLOR,
                fontname="helv",
            )

    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


def dimensions_to_csv_string(analysis: DrawingAnalysis) -> str:
    buf = io.StringIO()
    buf.write(f"שרטוט: {analysis.drawing_title}\n")
    buf.write(f"מספר חלק: {analysis.part_number}\n\n")
    buf.write("מספר,סוג מידה,ערך\n")
    for page in analysis.pages:
        for dim in page.dimensions:
            val_escaped = dim.value.replace('"', '""')
            type_escaped = dim.dimension_type.replace('"', '""')
            buf.write(f'{dim.number},"{type_escaped}","{val_escaped}"\n')
    return buf.getvalue()


def get_all_dimensions(analysis: DrawingAnalysis) -> list[DimensionItem]:
    dims: list[DimensionItem] = []
    for page in analysis.pages:
        dims.extend(page.dimensions)
    return dims
