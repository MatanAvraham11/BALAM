"""
PDF-to-CSV parser for Israeli purchasing orders (בל"מ).

Primary: deterministic regex parser (free, instant, 100% accurate).
Fallback: OpenAI GPT-4o with structured outputs (for unknown formats).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd
import pdfplumber
from openai import OpenAI
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Pydantic schema
# ---------------------------------------------------------------------------

class LineItem(BaseModel):
    supplier_sku: str = Field(description='מק"ט ספק')
    required_quantity: float = Field(description="כמות נדרשת")
    revision: str = Field(
        description=(
            'הוצאה – מתוך הסעיף "מסמכים הקשורים להזמנת הפריט". '
            'חפש את הדפוס "הוצאה:" (עם נקודתיים) וקח אך ורק את מה שאחרי הנקודתיים. '
            "הערך יכול להיות אות אנגלית בודדת (A, B, C, D…), קוד מספרי (00, 01…), או התו \"-\" בלבד. "
            "התעלם לחלוטין ממה שלפני המילה הוצאה (מופרד בפסיק) – זה שדה אחר (סוג). "
            'אם הערך הוא "-" החזר "-". '
            'אם אין ערך כלל, או שהמילה "הוצאה" לא מופיעה בכלל בסעיף, החזר "לא מצוין בבל\\"מ". '
        )
    )


class PurchaseOrder(BaseModel):
    balam_number: str = Field(description='מספר בל"מ')
    buyer_name: str = Field(
        description=(
            "שם הקניין – כל הערך המלא של שדה \"קניין שם\" בדיוק כפי שמופיע, "
            "כולל קוד או מספרים שמופיעים אחרי השם (למשל: \"S. Azoulay FE4\"). "
            "אין לקצר, אין לתרגם."
        )
    )
    customer_name: str = Field(
        default="",
        description=(
            "שם הלקוח (החברה שאליה שולחים את ההצעה). מופיע מתחת לכותרת "
            '"הערות קניין כלליות". יש לזהות לפי השם האנגלי של החברה ולהחזיר '
            'את השם המלא בעברית (למשל: "תעשייה אווירית לישראל בע\\"מ", '
            '"אלתא מערכות בע\\"מ").'
        ),
    )
    line_items: list[LineItem] = Field(
        description='רשימת שורות ההזמנה (מספר שורה 10, 20, 30 וכו\')'
    )


# ---------------------------------------------------------------------------
# 1. Text extraction
# ---------------------------------------------------------------------------

def extract_buyer_name(text: str) -> str | None:
    """Extract buyer name directly from text using regex (100% accurate).

    pdfplumber outputs Hebrew in visual order, so the label appears as
    ``ןיינק םש`` (reversed "שם קניין") with the value to its left.
    """
    match = re.search(r'(.+?) ןיינק םש', text)
    if match:
        raw = match.group(1).strip()
        # The value may have trailing non-buyer fields; take from end of line
        line_match = re.search(r'^(.+?) ןיינק םש', text, re.MULTILINE)
        if line_match:
            return line_match.group(1).strip()
        return raw
    return None


# Anchor that precedes the customer (recipient) block in every BLM template.
# pdfplumber returns Hebrew in visual (reversed) order — this is "הערות קניין כלליות".
_CUSTOMER_ANCHOR_RE = re.compile(r'תויללכ ןיינק תורעה')

# English keyword in the recipient block → canonical Hebrew customer name.
# Order matters: longer/more specific keywords first to avoid partial matches.
_CUSTOMER_KEYWORDS: list[tuple[str, str]] = [
    ("ISRAEL AEROSPACE", 'תעשייה אווירית לישראל בע"מ'),
    ("ELTA", 'אלתא מערכות בע"מ'),
    ("RAFAEL", 'רפאל מערכות לחימה מתקדמות בע"מ'),
    ("ELBIT", 'אלביט מערכות בע"מ'),
    ("IMI", "IMI Systems"),
]


def extract_customer_name(text: str) -> str | None:
    """Extract the customer (recipient) company name.

    The customer block sits right after the visual-reversed marker
    "הערות קניין כלליות". The first ~3 lines beneath it contain the company
    name in Hebrew (visual-reversed) and English. We match on the English
    keyword (LTR, stable across PDFs) and return a canonical Hebrew name.

    Falls back to the raw first line under the marker if no keyword matches,
    so the export never blocks; callers can later add a mapping entry.
    """
    anchor = _CUSTOMER_ANCHOR_RE.search(text)
    if not anchor:
        return None

    after = text[anchor.end():]
    next_lines = [line.strip() for line in after.splitlines() if line.strip()]
    window = " ".join(next_lines[:4]).upper()

    for keyword, canonical in _CUSTOMER_KEYWORDS:
        if keyword in window:
            return canonical

    return next_lines[0] if next_lines else None


def extract_text_from_pdf(pdf_path: str | Path) -> str:
    """Extract all text from *pdf_path* using pdfplumber."""
    pages: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""
            pages.append(f"--- Page {i} ---\n{text}")
    return "\n\n".join(pages)


# ---------------------------------------------------------------------------
# 2. Regex parser (primary – free, instant, deterministic)
# ---------------------------------------------------------------------------

# pdfplumber extracts Hebrew in visual (reversed) order — patterns below
# match the actual byte sequence in the extracted string.
_BALAM_RE = re.compile(r'(\d+) מ"לב רפסמ')
_BUYER_RE = re.compile(r'(.+?) ןיינק םש')
_EXPECTED_LINES_RE = re.compile(r'(\d+) תורוש רפסמ')
_LINE_START_RE = re.compile(r'הרוש רפסמ')
_SKU_RE = re.compile(r'([\w.\-/]+) קפס ט"קמ')
_QTY_RE = re.compile(r'([\d.]+) תשרדנ תומכ')
_REV_RE = re.compile(r'([A-Za-z0-9\-]+):האצוה')
_MISSING_REV = 'לא מצוין בבל"מ'


def parse_with_regex(text: str) -> PurchaseOrder | None:
    """Try to parse the BLM using regex only. Returns None if the format
    is unrecognised so the caller can fall back to LLM."""

    balam_m = _BALAM_RE.search(text)
    buyer_m = _BUYER_RE.search(text)
    if not balam_m or not buyer_m:
        return None

    balam_number = balam_m.group(1)
    buyer_name = buyer_m.group(1).strip()

    expected_m = _EXPECTED_LINES_RE.search(text)
    expected_count = int(expected_m.group(1)) if expected_m else None

    parts = _LINE_START_RE.split(text)
    # parts[0] = header, parts[1:] = each line-item chunk
    line_items: list[LineItem] = []
    for chunk in parts[1:]:
        sku_m = _SKU_RE.search(chunk)
        qty_m = _QTY_RE.search(chunk)
        if not sku_m or not qty_m:
            continue

        rev_m = _REV_RE.search(chunk)
        revision = rev_m.group(1) if rev_m else _MISSING_REV

        line_items.append(LineItem(
            supplier_sku=sku_m.group(1).strip(),
            required_quantity=float(qty_m.group(1)),
            revision=revision,
        ))

    if not line_items:
        return None

    if expected_count is not None and len(line_items) != expected_count:
        return None

    return PurchaseOrder(
        balam_number=balam_number,
        buyer_name=buyer_name,
        customer_name=extract_customer_name(text) or "",
        line_items=line_items,
    )


def _inherit_revision_for_last_item(items: list[LineItem]) -> None:
    """If the last line item has no revision but a sibling with the same SKU
    does, copy the sibling's revision so the downstream groupby aggregates
    them together."""
    if not items:
        return
    last = items[-1]
    if last.revision != _MISSING_REV:
        return
    for it in items[:-1]:
        if it.supplier_sku == last.supplier_sku and it.revision != _MISSING_REV:
            last.revision = it.revision
            return


def parse_balam_text(text: str) -> PurchaseOrder:
    """Parse BLM text: regex first (free & instant), GPT-4o fallback."""
    result = parse_with_regex(text)
    if result is not None:
        _inherit_revision_for_last_item(result.line_items)
        return result
    order = parse_with_openai(text)
    _inherit_revision_for_last_item(order.line_items)
    return order


# ---------------------------------------------------------------------------
# 3. LLM parsing (fallback for unknown formats)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
אתה מנתח מסמכי רכש (בל"מ) של צה"ל / משרד הביטחון בעברית.
תקבל טקסט שחולץ מקובץ PDF של הזמנת רכש.
עליך לחלץ את הנתונים הבאים בדיוק לפי ההוראות:

שדות גלובליים (שדה אחד לכל המסמך):
- balam_number: מספר בל"מ
- buyer_name: שם הקניין – יש להחזיר את **כל** הערך שמופיע בשדה "קניין שם" בדיוק כפי שהוא.
  הערך יכול לכלול שם ואחריו קוד/מספרים (למשל "S. Azoulay FE4" או "I. TAMIR F82").
  יש להחזיר את כל המחרוזת כולל הקוד בסוף, ללא קיצור, ללא תרגום.
- customer_name: שם הלקוח (החברה שאליה שולחים את ההצעה).
  מופיע מתחת לכותרת "הערות קניין כלליות" כמספר שורות עם השם בעברית ובאנגלית.
  זהה את החברה לפי השם האנגלי והחזר את השם המלא בעברית לדוגמה:
    "ISRAEL AEROSPACE INDUSTRIES LTD" → "תעשייה אווירית לישראל בע\"מ"
    "ELTA SYSTEMS LTD" → "אלתא מערכות בע\"מ"
    "RAFAEL" → "רפאל מערכות לחימה מתקדמות בע\"מ"
    "ELBIT" → "אלביט מערכות בע\"מ"

שורות הזמנה (line_items) – בדרך כלל מסומנות לפי "מספר שורה" (10, 20, 30...):
- supplier_sku: מק"ט ספק
- required_quantity: כמות נדרשת (מספר)
- revision: הוצאה

כללים קריטיים לשדה revision (הוצאה):
חשוב ביותר: כל שורת הזמנה (10, 20, 30…) היא עצמאית לחלוטין.
אין להעביר ערך מהוצאה של שורה אחת לשורה אחרת, גם אם הן דומות.

1. עבור כל שורה בנפרד, חפש את הסעיף "מסמכים הקשורים להזמנת הפריט" השייך לאותה שורה ספציפית.
2. אם לאותה שורה אין כלל סעיף "מסמכים הקשורים להזמנת הפריט" – החזר בדיוק: לא מצוין בבל"מ
3. אם הסעיף קיים, מצא את הדפוס "הוצאה:" (המילה "הוצאה" ואחריה נקודתיים).
4. הערך שאתה מחפש הוא מה שמופיע *אחרי הנקודתיים* של "הוצאה:".
   דוגמה: אם כתוב "סוג:ZEN,הוצאה:A" – הערך הנכון הוא A.
   דוגמה: אם כתוב "סוג:ZEN,הוצאה:-" – הערך הנכון הוא -.
5. אזהרה: מה שלפני המילה "הוצאה" (מופרד בפסיק) הוא שדה אחר (סוג).
   אל תחזיר אותו! החזר רק את מה שאחרי הנקודתיים.
6. הערך חייב להיות אות אנגלית בודדת (A, B, C, D…) או "-" בלבד.
   אם קיבלת יותר מתו אחד (למשל מילה שלמה) – כנראה לקחת שדה לא נכון.
7. אם הערך הוא "-", החזר בדיוק: -
8. אם המילה "הוצאה" לא מופיעה כלל, או אין ערך אחריה – החזר בדיוק: לא מצוין בבל"מ

חשוב: החזר את כל הנתונים בפורמט המבוקש בלבד, ללא הסברים נוספים.\
"""


def parse_with_openai(text: str) -> PurchaseOrder:
    """Send extracted text to OpenAI and return a validated PurchaseOrder."""
    client = OpenAI()

    completion = client.beta.chat.completions.parse(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        response_format=PurchaseOrder,
    )

    result = completion.choices[0].message.parsed
    if result is None:
        raise RuntimeError(
            "OpenAI returned a refusal or failed to parse the response."
        )

    buyer_name = extract_buyer_name(text)
    if buyer_name:
        result = result.model_copy(update={"buyer_name": buyer_name})

    if not result.customer_name:
        customer_name = extract_customer_name(text)
        if customer_name:
            result = result.model_copy(update={"customer_name": customer_name})

    return result


# ---------------------------------------------------------------------------
# 4. CSV export
# ---------------------------------------------------------------------------

def export_to_csv(order: PurchaseOrder, output_path: str | Path) -> Path:
    """Flatten *order* into a CSV with one row per line-item."""
    rows = [
        {
            "מקט ספק": item.supplier_sku,
            "כמות נדרשת": item.required_quantity,
            "הוצאה": item.revision,
        }
        for item in order.line_items
    ]

    df = pd.DataFrame(rows)
    out = Path(output_path)

    # newline='\r\n' makes Python translate any '\n' written to CRLF (Windows/Excel).
    with open(out, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(f'מספר בל"מ: {order.balam_number}\n')
        f.write(f"לקוח: {order.customer_name}\n")
        f.write(f"לידי: {order.buyer_name}\n")
        f.write("\n")
        df.to_csv(f, index=False)

    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "sample.pdf"
    pdf_file = Path(pdf_path)

    if not pdf_file.exists():
        print(f"Error: file not found – {pdf_file}")
        sys.exit(1)

    csv_path = pdf_file.with_suffix(".csv")

    print(f"Extracting text from {pdf_file} ...")
    text = extract_text_from_pdf(pdf_file)
    print(f"Extracted {len(text):,} characters from {pdf_file.name}.")

    print("Sending to OpenAI for parsing ...")
    order = parse_with_openai(text)
    print(
        f"Parsed successfully: balam={order.balam_number}, "
        f"buyer={order.buyer_name}, "
        f"{len(order.line_items)} line item(s)."
    )

    export_to_csv(order, csv_path)
    print(f"CSV saved to {csv_path}")


if __name__ == "__main__":
    main()
