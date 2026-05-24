# Rafael RFQ — שם קניין (OCR) — V.5.9 OCR.space

## מה המשמעות של `OCR Failed`

ב־[`api/parse_rafael_rfq.py`](../api/parse_rafael_rfq.py), השדה `buyer_name` מקבל את המחרוזת **`OCR Failed`** כש־**אין מפתח OCR.space** (`OCR_SPACE_API_KEY` ריק) או כש־`RAFAEL_BUYER_OCR` כבוי. **לא** נדרש Tesseract מקומי מאז V.5.9.

כשה־API רץ אבל אחרי הניקוי יש פחות מ־2 אותיות עבריות בטווח U+05D0–U+05EA, השדה נשאר **ריק** (`""`) — לא `OCR Failed`. בתגובת `POST /api/rafael-bom` אז `buyer_ocr_ready` יכול להיות `true` ו־`buyer_ocr_reason` יסביר למשל `ocr_space_no_hebrew`, `ocr_space_parse_empty`, `ocr_space_http_error` (ראו `rafael_buyer_ocr_api_status` ב־Python).

## מנוע OCR.space

עברית נתמכת ב־**OCREngine 3** (לפי תיעוד OCR.space). הפרסר מנסה `language=heb` עם מנועים **3 → 2 → 1**, ואם עדיין אין מספיק עברית — ניסוי נוסף עם `language=auto` ומנוע 3.

## אימות סביבה

1. **`OCR_SPACE_API_KEY`** — חובה בפריסת **Python** (Vercel env לפונקציית השרת / worker). הגדרה רק ב־Next (`.env.local`) לא מספיקה אם הפרסור רץ ב־Python נפרד.
2. **`RAFAEL_BUYER_OCR`** — לא להגדיר ל־`0` / `false` / `off` אם רוצים OCR.
3. בדיקה מהירה:

   ```bash
   python3 api/check_rafael_ocr_env.py
   ```

4. בדיקת PDF (דורש מפתח + רשת):

   ```bash
   export OCR_SPACE_API_KEY=...
   python3 api/test_rafael_ocr_space.py /path/to/RFQ.pdf
   ```

## Vercel / proxy

פריסת **worker** ב־Docker + **`RAFAEL_BOM_WORKER_URL`** עדיין נתמכת (אותו קוד Python); בקונטיינר מספיק להגדיר `OCR_SPACE_API_KEY` — אין צורך ב־Tesseract.

**תוכנית ארכיטקטורה (היסטורית):** [`plan-rafael-tesseract-production.md`](./plan-rafael-tesseract-production.md)

## קבצים רלוונטיים

| קובץ | תפקיד |
|------|--------|
| [`app/api/rafael-bom/route.ts`](../app/api/rafael-bom/route.ts) | Proxy ל־worker או ל־Python פנימי |
| [`docker/rafael-api/`](../docker/rafael-api/) | Docker + Fly לדוגמה |
| [`api/parse_rafael_rfq.py`](../api/parse_rafael_rfq.py) | `_rafael_buyer_ocr_probe`, `_buyer_name_from_ocr_space`, פרסור |
| [`api/test_rafael_ocr_space.py`](../api/test_rafael_ocr_space.py) | בדיקת טרמינל ל־`buyer_name` |
| [`api/index.py`](../api/index.py) | `POST /api/rafael-bom` — מחזיר `buyer_ocr_ready` / `buyer_ocr_reason` |
| [`api/check_rafael_ocr_env.py`](../api/check_rafael_ocr_env.py) | סקריפט בדיקה מהירה |
