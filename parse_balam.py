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
            'חפש את הדפוס "הוצאה:" (עם נקודתיים) וקח אך ורק את מה שאחרי הנקודתיים. '
            "הערך חייב להיות אות אנגלית בודדת (A, B, C, D…) או התו \"-\" בלבד. "
            "התעלם לחלוטין ממה שלפני המילה הוצאה (מופרד בפסיק) – זה שדה אחר (סוג). "
            'אם הערך הוא "-" החזר "-". '
            'אם אין ערך כלל החזר "לא מצוין בבל\\"מ". '
        )
    )


class PurchaseOrder(BaseModel):
    balam_number: str = Field(description='מספר בל"מ')
    buyer_name: str = Field(
        description="שם הקניין – בדיוק כפי שמופיע במסמך (עברית או אנגלית), ללא תרגום"
    )
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
- buyer_name: שם הקניין – יש להחזיר בדיוק כפי שמופיע במסמך.
  אם השם באנגלית, החזר באנגלית. אם בעברית, החזר בעברית. אל תתרגם.

שורות הזמנה (line_items) – בדרך כלל מסומנות לפי "מספר שורה" (10, 20, 30...):
- supplier_sku: מק"ט ספק
- required_quantity: כמות נדרשת (מספר)
- revision: הוצאה

כללים קריטיים לשדה revision (הוצאה):
1. חפש את הסעיף "מסמכים הקשורים להזמנת הפריט" עבור כל שורה.
2. מצא את הדפוס "הוצאה:" (המילה "הוצאה" ואחריה נקודתיים).
3. הערך שאתה מחפש הוא מה שמופיע *אחרי הנקודתיים* של "הוצאה:".
   דוגמה: אם כתוב "סוג ,הוצאה: A" – הערך הנכון הוא A.
   דוגמה: אם כתוב "סוג ,הוצאה: -" – הערך הנכון הוא -.
4. אזהרה: מה שלפני המילה "הוצאה" (מופרד בפסיק) הוא שדה אחר (סוג).
   אל תחזיר אותו! החזר רק את מה שאחרי הנקודתיים.
5. הערך חייב להיות אות אנגלית בודדת (A, B, C, D…) או "-" בלבד.
   אם קיבלת יותר מתו אחד (למשל מילה שלמה) – כנראה לקחת שדה לא נכון.
6. אם הערך הוא "-", החזר בדיוק: -
7. אם אין ערך כלל אחרי הנקודתיים (ריק או חסר), החזר בדיוק: לא מצוין בבל"מ

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
            'מק"ט ספק': item.supplier_sku,
            "כמות נדרשת": item.required_quantity,
            "הוצאה": item.revision,
        }
        for item in order.line_items
    ]

    df = pd.DataFrame(rows)
    out = Path(output_path)

    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        f.write(f'מספר בל"מ: {order.balam_number}\n')
        f.write(f"קניין: {order.buyer_name}\n")
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
