# Rafael RFQ — שם קניין (OCR) — V.5.9 OCR.space

## מה המשמעות של `OCR Failed`

ב־[`api/parse_rafael_rfq.py`](../api/parse_rafael_rfq.py), השדה `buyer_name` מקבל את המחרוזת **`OCR Failed`** כש־**אין מפתח OCR.space** (`OCR_SPACE_API_KEY` ריק) או כש־`RAFAEL_BUYER_OCR` כבוי. **לא** נדרש Tesseract מקומי מאז V.5.9.

כשה־API רץ אבל אחרי הניקוי יש פחות מ־2 אותיות עבריות בטווח U+05D0–U+05EA, השדה נשאר **ריק** (`""`) — לא `OCR Failed`. בתגובת `POST /api/rafael-bom` אז `buyer_ocr_ready` יכול להיות `true` ו־`buyer_ocr_reason` יסביר למשל `ocr_space_no_hebrew`, `ocr_space_rate_limited` (אחרי ניסיונות חוזרים), `ocr_space_network_error`, `ocr_space_quota_exceeded` (מכסה/קרדיטים בגוף JSON), `ocr_space_parse_empty`, וכו׳ (ראו `rafael_buyer_ocr_api_status` ב־Python).

## מנוע OCR.space

עברית נתמכת ב־**OCREngine 3** בלבד. Engine 1 דוחה `language=heb`/`auto` עם HTTP 400, לכן הוא הוסר מ־fallback. הסדר הוא: `language=heb` עם **Engine 3** → `language=auto` עם **Engine 3** → `language=auto` עם **Engine 2** (auto-detect). לכל שילוב יש עד **שלושה** ניסיונות HTTP עם השהיה קצרה, `User-Agent` תקני; ניסיון חוזר על קודים זמניים כולל **408, 429, 500, 502–504, 520–524**. סיווג שגיאות: רשת, 401/403, 429, 413/414, 400, 5xx, 4xx אחר, ורק אז «HTTP כללי». בתגובת ה־API ייתכן גם `buyer_ocr_http_status` (מספר) לצד `buyer_ocr_reason`.

**שינוי חשוב:** השליחה היא **multipart `file=`** (לא `base64Image`). שליחת `base64Image` בלי הקידומת `data:image/jpeg;base64,` גורמת ל-OCR.space להחזיר HTTP 400 ("Not a valid base64 image"). multipart גם חוסך ~33% נפח על החוט.

**V.6.0:** ב־`parse_rafael_rfq` נטען עמוד 1 פעם אחת ב־PyMuPDF, מרונדרים קרופ קניין + קרופ תאריך הגשה, ואז נשלחים ל־OCR.space (פחות פתיחות כפולות של אותו PDF). אם הקניין נכשל ב־`ocr_space_parse_empty` או `ocr_space_network_error`, מתבצע **ניסיון OCR חוזר אחד** לאחר השהיה קצרה.

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

## הקרופ הכירורגי לקניין

החל מ־V.5.9 (עדכון מאי 2026) הקרופ שנשלח ל־OCR.space מכיל **אך ורק** את הגליפים של השם, ללא:

- התווית `קניין:` (היא יושבת ב־`x ≈ 189–206pt`; ה־`clip_x1` נחתך ב־`email.x1 + 2 ≈ 183pt`, כלומר ברווח הבטוח בין סוף השם לתחילת התווית)
- התא `תאריך הדפסה:` שמעליו (נחתך על־ידי `clip_y0 = email.top − 27`)
- שורת הטלפון שמתחתיו (נחתכת על־ידי `clip_y1 = email.top − 13`)
- מסגרות התא

הכיול נעשה לפי מיקומי גליפי PUA של pdfplumber על שלוש קבצי RFQ ייחוס (`684471`, `684196`, `684070`). מאחר ש־OCR.space מקבל תמונה נקייה, פונקציית הניקוי `_buyer_ocr_label_clean` כעת מינימלית: הסרת תווים שאינם עבריים, מיזוג רווחים, בחירת רצף עברי ארוך ביותר, והשמטת מילים של אות אחת בקצוות.

**ניפוי שגיאות חזותי:** הגדר `RAFAEL_OCR_DEBUG=1` (ואופציונלית `RAFAEL_OCR_DEBUG_PATH=/path/to/file.png`) כדי לשמור את התמונה המדויקת שנשלחת ל־OCR.space אל `debug_crop.png` בתיקיית העבודה.

## דיוק שמות — מגבלות שנותרו

כל הרעש הסביבתי (תווית, תאים שכנים, מסגרות) נפתר על־ידי הקרופ הכירורגי. מה שעדיין עלול לקרות:

- **בלבול אותיות בתוך השם** — מנועי OCR מבלבלים אותיות דומות בפיקסלים: **י↔ו**, **י↔ף סופית**, ולפעמים מכפילים תווים (`שלאום` במקום `שלאם`, `סורנני` במקום `סורני`). אין תיקון אוטומטי: כל היוריסטיקה תשבור שמות אמיתיים (למשל «יוסף» אמיתי יהפוך ל־«יוסי»). אפשרויות שיפור מציאותיות:
   - **רזולוציית קרופ גבוהה יותר** (כרגע `300 DPI`; עלייה ל־`400-450 DPI` עלולה לעזור — מגדילה את משקל ה־JPEG ויש מגבלה ב־OCR.space free tier).
   - **מנוע אחר**: `Google Cloud Vision` / `Azure Read API` נותנים דיוק עברי טוב יותר מ־OCR.space ב־handwritten/low-DPI.
   - **מילון קניינים** — אם מתחזקים רשימה מוצקה של עובדים, אפשר להוסיף matching לקרוב ביותר (Levenshtein) לפני שמכריזים על שם סופי.
   - **תיקון ידני בייצוא** — לחיצה על תא «שם קניין» ב־UI ועריכה לפני שמירת ה־TSV.

## קבצים רלוונטיים

| קובץ | תפקיד |
|------|--------|
| [`app/api/rafael-bom/route.ts`](../app/api/rafael-bom/route.ts) | Proxy ל־worker או ל־Python פנימי |
| [`docker/rafael-api/`](../docker/rafael-api/) | Docker + Fly לדוגמה |
| [`api/parse_rafael_rfq.py`](../api/parse_rafael_rfq.py) | `_rafael_buyer_ocr_probe`, `_buyer_name_from_ocr_space`, פרסור |
| [`api/test_rafael_ocr_space.py`](../api/test_rafael_ocr_space.py) | בדיקת טרמינל ל־`buyer_name` |
| [`api/index.py`](../api/index.py) | `POST /api/rafael-bom` — מחזיר `buyer_ocr_ready` / `buyer_ocr_reason` |
| [`api/check_rafael_ocr_env.py`](../api/check_rafael_ocr_env.py) | סקריפט בדיקה מהירה |
