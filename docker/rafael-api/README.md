# Rafael Python API — Docker (Tesseract + עברית)

בנייה מהשורש של ה-repo:

```bash
docker build -f docker/rafael-api/Dockerfile -t rafael-api .
docker run --rm -p 8080:8080 \
  -e APP_SESSION_SECRET="same-as-vercel" \
  rafael-api
```

Fly.io: העתק את `fly.toml` מתוך התיקייה, עדכן `app =`, הרץ `fly deploy` מתוך שורש ה-repo (או הגדר `dockerfile` ב־`fly.toml`).

משתני סביבה חיוניים ל־auth (כמו ב־Vercel): `APP_SESSION_SECRET` — אותו ערך כמו בפריסת Next/Vercel.

ב־Vercel הגדר: `RAFAEL_BOM_WORKER_URL=https://<your-app>.fly.dev` (ללא סלאש בסוף).
