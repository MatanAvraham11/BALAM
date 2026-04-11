"""
PDF-to-CSV parser for Israeli purchasing orders (בל"מ).

Extracts text from a Hebrew PDF, sends it to OpenAI gpt-4o with
structured outputs (Pydantic), and exports a flat CSV.
"""

from __future__ import annotations

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
            'אם הערך הוא "-" יש להחזיר "-". '
            'אם הערך חסר או ריק לחלוטין יש להחזיר "לא צוין בבל\\"מ". '
            "אחרת יש להחזיר את הערך המדויק."
        )
    )


class PurchaseOrder(BaseModel):
    balam_number: str = Field(description='מספר בל"מ')
    buyer_name: str = Field(description="שם קניין")
    line_items: list[LineItem] = Field(
        description='רשימת שורות ההזמנה (מספר שורה 10, 20, 30 וכו\')'
    )


# ---------------------------------------------------------------------------
# 1. Text extraction
# ---------------------------------------------------------------------------

def extract_text_from_pdf(pdf_path: str | Path) -> str:
    """Extract all text from *pdf_path* using pdfplumber."""
    pages: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""
            pages.append(f"--- Page {i} ---\n{text}")
    return "\n\n".join(pages)


# ---------------------------------------------------------------------------
# 2. LLM parsing
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
אתה מנתח מסמכי רכש (בל"מ) של צה"ל / משרד הביטחון בעברית.
תקבל טקסט שחולץ מקובץ PDF של הזמנת רכש.
עליך לחלץ את הנתונים הבאים בדיוק לפי ההוראות:

שדות גלובליים (שדה אחד לכל המסמך):
- balam_number: מספר בל"מ
- buyer_name: שם הקניין

שורות הזמנה (line_items) – בדרך כלל מסומנות לפי "מספר שורה" (10, 20, 30...):
- supplier_sku: מק"ט ספק
- required_quantity: כמות נדרשת (מספר)
- revision: הוצאה

כללים קריטיים לשדה revision (הוצאה):
1. חפש את הסעיף "מסמכים הקשורים להזמנת הפריט" עבור כל שורה.
2. מצא את המילה "הוצאה" בסעיף הזה.
3. אם הערך שליד "הוצאה" הוא "-", החזר בדיוק: -
4. אם הערך חסר לחלוטין או ריק, החזר בדיוק: לא צוין בבל"מ
5. אם יש ערך כלשהו (למשל "ZEN", "00", "B"), החזר אותו כפי שהוא.

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
    return result


# ---------------------------------------------------------------------------
# 3. CSV export
# ---------------------------------------------------------------------------

def export_to_csv(order: PurchaseOrder, output_path: str | Path) -> Path:
    """Flatten *order* into a CSV with one row per line-item."""
    rows = [
        {
            "Balam Number": order.balam_number,
            "Buyer Name": order.buyer_name,
            "Supplier SKU": item.supplier_sku,
            "Required Quantity": item.required_quantity,
            "Revision": item.revision,
        }
        for item in order.line_items
    ]

    df = pd.DataFrame(rows)
    out = Path(output_path)
    df.to_csv(out, index=False, encoding="utf-8-sig")
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
