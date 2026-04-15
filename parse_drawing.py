"""
Engineering-drawing dimension extractor.

Converts a PDF drawing to an image, sends it to GPT-4o Vision for
structured dimension extraction, annotates the original PDF with
numbered labels, and produces a CSV of all dimensions.
"""

from __future__ import annotations

import base64
import io
import re
from pathlib import Path

import fitz  # PyMuPDF
from openai import OpenAI
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Pydantic schema
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
            "ערך המידה בדיוק כפי שמופיע בשרטוט, כולל טולרנסים אם קיימים. "
            'לדוגמה: "59.0 ±0.05", "⌀6.35", "R0.50", "#6-32UNC-2A", '
            '"PASSIVATION PER AMS 2700"'
        )
    )
    x_pct: float = Field(
        description="מיקום X של המידה כאחוז מרוחב התמונה (0.0 = שמאל, 1.0 = ימין)"
    )
    y_pct: float = Field(
        description="מיקום Y של המידה כאחוז מגובה התמונה (0.0 = למעלה, 1.0 = למטה)"
    )


class DrawingPage(BaseModel):
    dimensions: list[DimensionItem] = Field(
        description="רשימת כל המידות וההערות שזוהו בעמוד זה"
    )


class DrawingAnalysis(BaseModel):
    drawing_title: str = Field(description="שם החלק / כותרת השרטוט")
    part_number: str = Field(description="מספר חלק (Part Number / DWG Number)")
    pages: list[DrawingPage] = Field(description="ניתוח לכל עמוד בשרטוט")


# ---------------------------------------------------------------------------
# Vision system prompt
# ---------------------------------------------------------------------------

DRAWING_SYSTEM_PROMPT = """\
You are an expert engineering drawing analyst. You receive a high-resolution \
image of a single page from a technical/engineering drawing (mechanical part).

Your task is to identify **every dimension, tolerance, GD&T callout, and note** \
visible on this page and return them as a structured list.

## NUMBERING RULES (CRITICAL)
1. Start numbering from the **NOTES section** (usually top-left area). \
Each note bullet point is a separate item.
2. After the notes, continue numbering **clockwise** around the drawing, \
starting from the top-left corner of the drawing views.
3. Process all views (main view, sections, details) in clockwise order.
4. Numbers must be sequential with no gaps: 1, 2, 3, 4, ...

## WHAT COUNTS AS A DIMENSION
- Any numerical value with dimension lines/arrows (linear dimensions)
- Diameter symbols (⌀) with values
- Radius symbols (R) with values
- Angles
- Thread callouts (e.g., #6-32UNC-2A, M8x1.25)
- Tolerances shown on dimensions (include them as part of the value)
- GD&T callouts (flatness, perpendicularity, parallelism, concentricity, etc.)
- Surface finish symbols (Ra values)
- Chamfer callouts (e.g., 0.3x45°)
- Each individual note in the NOTES section (type = "הערה (Note)")

## DIMENSION TYPE CLASSIFICATION
You MUST classify each dimension using EXACTLY one of these types:
""" + "\n".join(f"- {t}" for t in DIMENSION_TYPES) + """

## COORDINATE RULES
- Return x_pct and y_pct as fractions from 0.0 to 1.0.
- x_pct = 0.0 is the LEFT edge, 1.0 is the RIGHT edge.
- y_pct = 0.0 is the TOP edge, 1.0 is the BOTTOM edge.
- Place the coordinate RIGHT NEXT TO the dimension value text on the drawing, \
slightly offset so the annotation circle won't overlap the value itself.

## VALUE RULES
- Copy the dimension value EXACTLY as shown, including ± tolerances, \
+/- limits, symbols (⌀, R, °), etc.
- For notes, copy the full text of the note bullet.
- Do NOT translate or interpret values.

## IMPORTANT
- Be thorough: do NOT miss any dimension or note.
- Each item must have a unique sequential number.
- If a dimension appears multiple times (e.g., "4X ⌀3.05"), \
list it once with the multiplier included in the value.
"""


# ---------------------------------------------------------------------------
# 1. PDF page → image
# ---------------------------------------------------------------------------

def pdf_page_to_image(pdf_path: str | Path, page_num: int = 0, dpi: int = 200) -> bytes:
    """Render a single PDF page to a PNG image at the given DPI."""
    doc = fitz.open(str(pdf_path))
    page = doc[page_num]
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img_bytes = pix.tobytes("png")
    doc.close()
    return img_bytes


def get_page_count(pdf_path: str | Path) -> int:
    """Return the number of pages in a PDF."""
    doc = fitz.open(str(pdf_path))
    count = len(doc)
    doc.close()
    return count


# ---------------------------------------------------------------------------
# 2. GPT-4o Vision analysis
# ---------------------------------------------------------------------------

def _image_to_data_url(img_bytes: bytes) -> str:
    b64 = base64.b64encode(img_bytes).decode()
    return f"data:image/png;base64,{b64}"


def analyze_drawing_page(img_bytes: bytes, start_number: int = 1) -> DrawingPage:
    """Send a single page image to GPT-4o Vision and get structured dimensions."""
    client = OpenAI()

    user_content: list[dict] = [
        {
            "type": "text",
            "text": (
                f"Analyze this engineering drawing page. "
                f"Start numbering from {start_number}. "
                f"Identify every dimension, tolerance, GD&T callout, and note. "
                f"Number them clockwise starting from NOTES (top-left), then "
                f"proceeding clockwise around all views."
            ),
        },
        {
            "type": "image_url",
            "image_url": {
                "url": _image_to_data_url(img_bytes),
                "detail": "high",
            },
        },
    ]

    completion = client.beta.chat.completions.parse(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": DRAWING_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format=DrawingPage,
        max_tokens=16000,
    )

    result = completion.choices[0].message.parsed
    if result is None:
        raise RuntimeError("GPT-4o returned a refusal or failed to parse the drawing.")
    return result


def analyze_full_drawing(pdf_path: str | Path) -> DrawingAnalysis:
    """Analyze all pages of a drawing PDF and return combined results."""
    num_pages = get_page_count(pdf_path)
    client = OpenAI()

    all_pages: list[DrawingPage] = []
    start_number = 1

    for page_idx in range(num_pages):
        img_bytes = pdf_page_to_image(pdf_path, page_num=page_idx, dpi=200)
        page_result = analyze_drawing_page(img_bytes, start_number=start_number)
        all_pages.append(page_result)
        if page_result.dimensions:
            start_number = max(d.number for d in page_result.dimensions) + 1

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
        title_info = _TitleInfo(drawing_title="Unknown", part_number="Unknown")

    return DrawingAnalysis(
        drawing_title=title_info.drawing_title,
        part_number=title_info.part_number,
        pages=all_pages,
    )


class _TitleInfo(BaseModel):
    drawing_title: str = Field(description="Drawing title from the title block")
    part_number: str = Field(description="Part number / DWG number from the title block")


# ---------------------------------------------------------------------------
# 3. Text-span extraction (for accurate annotation placement)
# ---------------------------------------------------------------------------

def extract_text_spans(pdf_path: str | Path, page_num: int = 0) -> list[dict]:
    """Return every text span on *page_num* with its exact PDF bounding box."""
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
    """Pull searchable tokens from a GPT dimension value string.

    For ``"59.0 ±0.05"`` → ``["59.0", "0.05"]``
    For ``"#6-32UNC-2A"`` → ``["6-32UNC-2A", "6", "32"]``
    For ``"R0.50"``        → ``["0.50"]``
    For ``"PASSIVATION PER AMS 2700"`` → ``["PASSIVATION", "2700"]``
    """
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
    """Find the PDF text span that best matches *value* and return (cx, cy).

    Uses the GPT approximate coordinate as a tiebreaker when multiple spans
    contain the same token.  Falls back to the GPT coordinate when no
    text-span match is found (e.g. scanned / image-only PDFs).
    """
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
# 4. PDF annotation
# ---------------------------------------------------------------------------

_CIRCLE_RADIUS = 10
_FONT_SIZE = 7
_LABEL_COLOR = (1, 0, 0)  # red
_CIRCLE_FILL = (1, 1, 1)  # white fill for readability
_CIRCLE_BORDER = (1, 0, 0)  # red border
_CIRCLE_OFFSET = 2  # gap between circle edge and dimension text


def annotate_pdf(pdf_path: str | Path, analysis: DrawingAnalysis) -> bytes:
    """Draw numbered circles on the original PDF next to each dimension.

    Uses exact text-span bounding boxes from PyMuPDF for placement,
    falling back to the GPT-estimated coordinates for scanned PDFs.
    Returns the annotated PDF as bytes.
    """
    doc = fitz.open(str(pdf_path))

    for page_idx, page_analysis in enumerate(analysis.pages):
        if page_idx >= len(doc):
            break
        page = doc[page_idx]
        rect = page.rect
        pw, ph = rect.width, rect.height

        spans = extract_text_spans(pdf_path, page_num=page_idx)

        for dim in page_analysis.dimensions:
            anchor_x, anchor_y = find_span_for_value(
                dim.value, spans, dim.x_pct, dim.y_pct, pw, ph,
            )

            cx = anchor_x - _CIRCLE_RADIUS - _CIRCLE_OFFSET
            cy = anchor_y

            cx = max(_CIRCLE_RADIUS, min(pw - _CIRCLE_RADIUS, cx))
            cy = max(_CIRCLE_RADIUS, min(ph - _CIRCLE_RADIUS, cy))

            shape = page.new_shape()
            shape.draw_circle(fitz.Point(cx, cy), _CIRCLE_RADIUS)
            shape.finish(
                color=_CIRCLE_BORDER,
                fill=_CIRCLE_FILL,
                width=0.8,
            )
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


# ---------------------------------------------------------------------------
# 4. CSV generation
# ---------------------------------------------------------------------------

def dimensions_to_csv_string(analysis: DrawingAnalysis) -> str:
    """Build a CSV string from the analysis results."""
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
    """Flatten all dimensions from all pages into a single list."""
    dims: list[DimensionItem] = []
    for page in analysis.pages:
        dims.extend(page.dimensions)
    return dims
