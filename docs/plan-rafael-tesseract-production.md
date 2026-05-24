# תוכנית: פתרון "חסר Tesseract בשרת" בפרודקשן (Rafael V.5.7)

## סטטוס יישום (אפשרות A)

נוספו בפרויקט:

| רכיב | תיאור |
|------|--------|
| [`docker/rafael-api/Dockerfile`](../docker/rafael-api/Dockerfile) | Python 3.12 + `tesseract-ocr` + `tesseract-ocr-heb` + `uvicorn api.index:app` |
| [`docker/rafael-api/README.md`](../docker/rafael-api/README.md) | בניית image והרצה מקומית |
| [`docker/rafael-api/fly.toml.example`](../docker/rafael-api/fly.toml.example) | דוגמה ל־Fly.io |
| [`app/api/rafael-bom/route.ts`](../app/api/rafael-bom/route.ts) | Proxy: worker אם `RAFAEL_BOM_WORKER_URL`, אחרת פנימי ל־Python |
| [`vercel.json`](../vercel.json) | `/api/rafael-bom` מטופל ב־Next; רק `/api/internal/rafael-bom` → Python |
| [`api/index.py`](../api/index.py) | אותו handler ל־`POST /api/rafael-bom` ו־`POST /api/internal/rafael-bom` |

**פריסת Vercel:** הגדר `RAFAEL_BOM_WORKER_URL` לכתובת ה־worker (HTTPS). אותו `APP_SESSION_SECRET` כמו ב־Next.

**פיתוח:** `vercel dev` או `PYDEV_API_BASE_URL=http://127.0.0.1:8000` עם `uvicorn api.index:app --port 8000` (מ־שורש repo, `PYTHONPATH` = שורש).

---

## למה זה חוזר אחרי תיקוני PATH

ההודעה **`tesseract_not_on_path`** (ב־UI: «חסר Tesseract בשרת — אין בינארי ב־PATH») מופיעה כש־**לא נמצא קובץ הרצה של Tesseract** בתהליך ה־Python שמריץ את `POST /api/rafael-bom`.

- **מקומי / Mac עם Homebrew:** לרוב כבר יש בינארי; הקוד מחפש גם ב־`/opt/homebrew/bin` וכו'. אם עדיין רואים את ההודעה — כנראה תהליך אחר או env שגוי.
- **Vercel (Python Serverless):** ב־image של הפונקציה **אין בכלל** `tesseract` מותקן. **לא ניתן** לפתור זאת רק עם משתני סביבה או `TESSERACT_CMD` — חייב להופיע קובץ בינארי (או להחליף את שכבת ה־OCR).

מסקנה: **הפריסה הנוכחית ב־Vercel (`vercel.json` → `/api/index`) לא יכולה להריץ OCR מקומי בלי שינוי ארכיטקטורה.**

---

## יעד מוצר

שדה **שם קניין** יתמלא מ־OCR עברית (או לפחות לא יישאר תקוע על שגיאת תשתית), כאשר המשתמש מעלה RFQ בפרודקשן — בלי להסתמך על התקנה על מחשב המפתח בלבד.

---

## אפשרויות (לפי סדר מומלץ לרוב הפרויקטים)

### אפשרות A — **Worker עם Docker** (מומלץ אם רוצים להישאר על לוגיקת Tesseract הקיימת)

**רעיון:** להריץ את אותו קוד Python (`parse_rafael_rfq` + `pytesseract`) על שירות שמאפשר **Dockerfile** עם:

- `apt-get install -y tesseract-ocr tesseract-ocr-heb` (או מקביל),
- `requirements.txt` כמו היום.

**פלטפורמות טיפוסיות:** Google Cloud Run, Fly.io, Railway, Render (עם Docker).

**שינוי באפליקציה:**

1. לפרוס את ה־API (או רק נתיב `rafael-bom`) כשירות נפרד עם URL קבוע, למשל `https://rafael-api.example.com`.
2. ב־**Vercel / Next** — אחת מהשתיים:
   - **Rewrite / proxy:** נתיב Next `app/api/rafael-bom` שמעביר `multipart` ל־worker (שומר על אותו חוזה ללקוח), או
   - **משתנה סביבה** בצד לקוח: `NEXT_PUBLIC_…` (פחות אידיאלי — חושף URL).

**יתרונות:** שומר על Tesseract + `heb` + הקרופ הקיים; שליטה מלאה.  
**חסרונות:** שני שירותים לתחזק, סודות/אימות בין Vercel ל־worker.

**צ'קליסט יישום (A):**

| # | משימה | סטטוס |
|---|--------|--------|
| 1 | Dockerfile: `FROM python:3.12-slim`, התקנת `tesseract-ocr` + `tesseract-ocr-heb`, `COPY api/`, `pip install -r requirements.txt` | ✅ `docker/rafael-api/Dockerfile` |
| 2 | `CMD` עם `uvicorn` ל־`api.index:app` | ✅ באותו Dockerfile |
| 3 | אימות עם cookie — ליישר עם `_require_auth` | ✅ אותו handler; העברת `Cookie` מה־proxy |
| 4 | פריסת worker + URL יציב | ⏳ אצלך (Fly/Railway/…) |
| 5 | שינוי Next/Vercel: proxy + env | ✅ `RAFAEL_BOM_WORKER_URL`, `vercel.json`, `app/api/rafael-bom/route.ts` |
| 6 | בדיקות E2E RFQ אמיתי | ⏳ אחרי פריסת worker |

---

### אפשרות B — **כל ה־Python API על VM / שרת אחד** (פשוט תפעולית, פחות "ענן נקי")

**רעיון:** לא לפרסר Rafael על Vercel בכלל; שרת Linux (VPS, EC2) עם `apt install tesseract-ocr-heb` ו־reverse proxy ל־`/api/*`.

**יתרונות:** פתרון אחד, Tesseract עובד כמו במקומי.  
**חסרונות:** ניהול שרת, SSL, עדכונים.

---

### אפשרות C — **OCR בענן (Vision / Textract / אחר)**

**רעיון:** אחרי יצירת תמונת הקרופ (PyMuPDF), לשלוח תמונה ל־API חיצוני ולקבל טקסט; **אין צורך** ב־Tesseract על השרת.

**יתרונות:** מתאים ל־serverless "רזה".  
**חסרונות:** עלות לפי שימוש, מפתח API, שינוי קוד ב־`parse_rafael_rfq` (ענף חדש), שיקולי פרטיות (תוכן RFQ).

**צ'קליסט יישום (C):**

| # | משימה |
|---|--------|
| 1 | בחירת ספק והגדרת `*_API_KEY` ב־env (לא בקומיט) |
| 2 | פונקציה `buyer_name_from_cloud_ocr(image: bytes) -> str` + fallback ל־Tesseract כשקיים מקומית |
| 3 | בדיקות יחידה + RFQ אחד לפחות ב־staging |

---

### אפשרות D — **הישארות על Vercel בלי שם קניין ב־OCR**

**רעיון:** לקבל במוצר שבפרודקשן שם קניין יישאר ריק / "לא זמין" עד שיעבור ל־A/B/C.

**יתרונות:** אפס עבודת תשתית.  
**חסרונות:** לא פותר את הדרישה העסקית אם חייבים שם קניין.

---

## המלצה פרקטית

1. **קצר טווח (אם חייבים שם קניין בפרודקשן):** **אפשרות A** (Cloud Run / Fly + Docker) עם proxy מ־Next.  
2. **אם העלות/תחזוקה של שני שירותים כבדה:** **אפשרות C** לשכבת OCR בלבד, שאר הפרסור נשאר ב־Vercel (אם זיכרון/זמן ריצה מאפשרים — אולי צריך גם להעביר את כל `rafael-bom` ל־worker בגלל גודל PDF).

---

## אימות לפני/אחרי

- **ב־אותו סביבה שבה רץ ה־API בפרודקשן:** הרצת  
  `python3 api/check_rafael_ocr_env.py`  
  (או לוג בזמן בקשה: `buyer_ocr_ready` / `buyer_ocr_reason` ב־JSON).
- **יעד:** `buyer_ocr_ready: true`, `buyer_ocr_reason: null`, ושם קניין בעברית ב־≥2 אותיות.

---

## קישורים בפרויקט

- רקע טכני ו־env מקומי: [`rafael-buyer-ocr.md`](./rafael-buyer-ocr.md)
- נקודת הכניסה ל־API: [`api/index.py`](../api/index.py) — `POST /api/rafael-bom`
- זיהוי Tesseract: [`api/parse_rafael_rfq.py`](../api/parse_rafael_rfq.py) — `_resolved_tesseract_executable`, `_tesseract_probe`

---

## סיכום משפט אחד

**ב־Vercel אין Tesseract; צריך או runtime עם Docker/שרת שיש בו Tesseract+heb, או OCR חיצוני — לא עוד התאמות PATH.**
