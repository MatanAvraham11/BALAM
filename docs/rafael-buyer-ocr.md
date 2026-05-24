# Rafael RFQ — שם קניין (OCR) והודעת "OCR Failed"

## מה המשמעות של `OCR Failed`

ב־[`api/parse_rafael_rfq.py`](../api/parse_rafael_rfq.py), השדה `buyer_name` מקבל את המחרוזת **`OCR Failed`** רק כש־**מחסנית ה־OCR לא זמינה** (אין Tesseract ב־PATH, אין חבילת `heb`, או `RAFAEL_BUYER_OCR` כבוי). זה **לא** תיקון קרופ בלבד.

כשה־OCR רץ אבל אחרי הניקוי יש פחות מ־2 אותיות עבריות בטווח U+05D0–U+05EA, השדה נשאר **ריק** (`""`) — לא `OCR Failed`.

## אימות סביבה (מקומי / שרת)

1. **משתנה סביבה** — ודא ש־`RAFAEL_BUYER_OCR` **לא** מוגדר ל־`0` / `false` / `off` (ראו `.env.local.example`).
2. **מיקום Tesseract** — הקוד מחפש לפי הסדר: `TESSERACT_CMD` / `RAFAEL_TESSERACT_CMD` (נתיב מלא), אחר כך `which tesseract`, ואז נתיבים נפוצים (`/opt/homebrew/bin/tesseract`, `/usr/local/bin/tesseract`, `/usr/bin/tesseract`). אם עדיין מקבלים `tesseract_not_on_path`, הגדר אחד ממשתני ה־CMD לנתיב המלא שבו `tesseract` מותקן.
3. **רשימת שפות** — באותו תהליך שמריץ את ה־Python של ה־API:
   - `which tesseract` (או הנתיב מה־CMD)
   - `tesseract --list-langs` — חייבת להופיע **`heb`**.
4. **Python** — מהתיקייה עם `api/` ב־`PYTHONPATH` (או מתוך `api/`):

   ```bash
   python3 api/check_rafael_ocr_env.py
   ```

   או:

   ```bash
   cd api && python3 -c "from parse_rafael_rfq import rafael_buyer_ocr_diagnostic; print(rafael_buyer_ocr_diagnostic())"
   ```

## Vercel / Serverless

ב־**Vercel Python Serverless** אין בדרך כלל Tesseract מותקן, ולכן `buyer_ocr_ready` יהיה `false` והממשק יציג הסבר (לפי `buyer_ocr_reason` מה־API).

אפשרויות אמיתיות:

1. **Docker / image מותאם** עם `tesseract`, `tesseract-lang` (עברית), ו־`pytesseract`.
2. **Worker נפרד** (EC2, Cloud Run, וכו') שמריץ את אותו קוד Python עם Tesseract, והלקוח שולח אליו את ה־PDF.
3. **שירות OCR חיצוני** — העלאת תמונת הקרופ, קבלת טקסט; דורש שינוי קוד נוסף.

## קבצים רלוונטיים

| קובץ | תפקיד |
|------|--------|
| [`api/parse_rafael_rfq.py`](../api/parse_rafael_rfq.py) | `_tesseract_probe`, `rafael_buyer_ocr_diagnostic`, פרסור |
| [`api/index.py`](../api/index.py) | `POST /api/rafael-bom` — מחזיר `buyer_ocr_ready` / `buyer_ocr_reason` |
| [`api/check_rafael_ocr_env.py`](../api/check_rafael_ocr_env.py) | סקריפט בדיקה מהירה |
