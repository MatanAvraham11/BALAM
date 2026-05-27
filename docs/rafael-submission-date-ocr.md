# Rafael RFQ — תאריך סופי להגשה (OCR) — V.6.0

## בעיה

ב־PDF של רפאל, שורת המשפט **«המענה יוגש לא יאוחר מיום DD/MM/YYYY בשעה …»** לרוב **לא** מופיעה בשכבת הטקסט של `extract_text()` (פונט subset / CMap שבור). לעומת זאת, תאריכים בפורמט `dd/mm/yyyy` **כן** מופיעים לפעמים בעמודים פנימיים — ואז בחירת «התאריך הראשון בטקסט» עלולה לתת **תאריך שגוי** (לא תאריך ההגשה הסופית).

## פתרון (V.6.0)

1. **קרופ כירורגי** לשורת המועד בעמוד 1 (כיסוי), ב־300 DPI, לפי אנכי יחסית לשורת האימייל `…@rafael.co.il`. אופקית: חלון **`anchor_x0 − 85 … anchor_x0 + 25`** (נרמול מ־120/10; ראו `_SUB_DUE_*` ב־[`api/parse_rafael_rfq.py`](../api/parse_rafael_rfq.py)).
2. **OCR.space** — סדר ניסיונות: `eng` → `heb` → `auto` (מנועים 3 ואז 2), מתאים למחרוזות ספרות ו־`/`.
3. **Regex קשיח**: `\d{2}/\d{2}/\d{4}` אחרי נרמול מקף/מינוס, עם אימות `_parse_dmy`.
4. אם OCR לא זמין או לא מחזיר תאריך תקף — נשאר **fallback**: סריקת `extract_text()` לפי סדר עמודים, ואז תאריך ההפקה.

## שדות API / מודל

- `submission_date` — ערך ה־`dd/mm/yyyy` הסופי (כמו קודם).
- `submission_due_date` — **אותו ערך** (שדה מחושב ב־Pydantic לנוחות לקוח / JSON).

## ניפוי שגיאות

- `RAFAEL_OCR_DEBUG=1` — שומר גם את קרופ תאריך ההגשה ל־`debug_date_crop.png` (או `RAFAEL_OCR_DEBUG_DATE_PATH`).
- סקריפט: `python3 api/test_ocr_crop.py /path/to/RFQ.pdf` — יוצר `debug_crop.png` ו־`debug_date_crop.png` ומדפיס את תוצאת ה־OCR לשם.

## קבצים

| קובץ | תפקיד |
|------|--------|
| [`api/parse_rafael_rfq.py`](../api/parse_rafael_rfq.py) | `_submission_due_date_from_ocr_space`, `_detect_submission_date` |
| [`api/test_ocr_crop.py`](../api/test_ocr_crop.py) | יצוא קרופים ל־PNG + הדפסת OCR |
| [`docs/rafael-buyer-ocr.md`](./rafael-buyer-ocr.md) | קניין (OCR.space) |
