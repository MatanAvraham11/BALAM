# Rafael PLR / ZIP — Phase 2 (V.6.1)

מסמך זה מתאר את מבנה ה-ZIP הנתמך, שרשרת ה-fallback לפענוח הקבצים, עמודות הפלט, וקודי השגיאה.

---

## מבנה ZIP מצופה

```
TransferRequest_*.zip          ← עטיפה חיצונית (אופציונלי)
└── <id>_1_PRODUCT.ZIP         ← ה-ZIP האמיתי
    └── data/files/            ← אותיות קטנות
        ├── PLReport_<PN>_*.zip  ← כל PLR הוא ZIP מקונן
        │   └── <PN>_<rev>_*.xls ← CDFV2 בינארי או dirty CSV
        ├── *_MLEDR Report_*.xls
        └── *.pdf / *.stp / …
```

### כללים לניתוב
- אם ה-ZIP שהועלה מכיל חבר **יחיד** שמסתיים ב-`_PRODUCT.ZIP` — נכנסים לתוכו.
- אחרת מניחים שה-ZIP שהועלה הוא עצמו ה-Product ZIP.
- מתחת ל-`data/files/` מסננים שמות שמתחילים ב-`PLReport` או `PLR_` (case-insensitive).
- אם חבר מסונן הוא עצמו ZIP — מחלצים את ה-`.xls/.csv` שבתוכו.

---

## שרשרת Fallback לפענוח PLR

1. **CSV (Pass 1)**: `csv.reader` עם מפריד פסיק.  
   מאתר שורת `Part List for: <PN>` ושורת header עם `Operation Sequence` + `Component Item`.  
   עובד גם על קבצים שנראים כ-XLS אך הם בעצם CSVs.

2. **Binary XLS (Pass 2)**: `pandas.read_excel(..., engine="xlrd", header=None, dtype=str)`.  
   נדרש ל-CDFV2 Excel 97–2003.

3. **XLSX (Pass 3)**: `pandas.read_excel(..., engine="openpyxl", header=None, dtype=str)`.  
   מופעל רק אם הקובץ מתחיל ב-`PK\x03\x04` (magic bytes של ZIP/XLSX) וה-Passes הקודמים נכשלו.

---

## עמודות תוצאה

| שדה               | תיאור                                   |
|-------------------|-----------------------------------------|
| `row_number`      | מספר שורה סידורי 1-based עבור כל הפלט. |
| `operation_sequence` | שדה "Operation Sequence" מה-PLR.    |
| `component_item`  | שדה "Component Item" מה-PLR.           |

### מטא-נתונים בפלט

| שדה                  | תיאור                                                                   |
|----------------------|-------------------------------------------------------------------------|
| `matched_file_count` | כמה קבצי PLR שה-PN שלהם == `parent_part_number` (שורותיהם בראש הרשימה). |
| `total_file_count`   | סה״כ קבצי PLR שנמצאו.                                                   |
| `warnings`           | רשימת אזהרות לא-קריטיות (קבצים מדולגים, PN חסר וכד׳).                  |

---

## לוגיקת מיון

שורות מקבצי PLR שה-PN שלהם תואם בדיוק ל-`parent_part_number` (case-insensitive) עוברות לראש הרשימה המאוחדת. שאר השורות מצורפות בסדר ההופעה.

`parent_part_number` הוא ה-`rafael_pn` הראשון מתוצאות ה-PDF שחולץ קודם לכן.

---

## קודי שגיאה וסיטואציות

| מצב                                      | HTTP | תגובה                                                                                |
|------------------------------------------|------|--------------------------------------------------------------------------------------|
| ZIP ריק / לא נשלח                        | 400  | `{"detail": "קובץ ZIP ריק."}`                                                       |
| ZIP פגום (BadZipFile)                    | 400  | `{"detail": "לא ניתן לפתוח את ה-ZIP: …"}`                                           |
| אין `data/files/PLR*` בתוך ה-ZIP         | 200  | `{"rows": [], "warnings": ["לא נמצאו קבצי PLReport_* …"]}`                          |
| קובץ PLR ללא שורת `Part List for:`       | 200  | `{"rows": [], "warnings": ["<filename>: לא נמצאה שורת Part List …"]}`               |
| קובץ PLR ללא שורות נתונים מתחת ל-header | 200  | `{"rows": [], "warnings": ["<filename>: לא נמצאו שורות נתונים …"]}`                 |
| ZIP פנימי מקונן פגום                     | 200  | `{"rows": [], "warnings": ["<filename>: הזיפ המקונן פגום …"]}`                     |
| ZIP גדול מ-50 MB                         | 200  | `{"rows": [], "warnings": ["ZIP גדול מדי (N MB); המקסימום הוא 50 MB."]}`            |
| auth נדחה                                | 401  | `{"detail": "Unauthorized"}`                                                         |

---

## אינטגרציה בצד הלקוח

1. **שני Dropzones**: אחד ל-PDF (קיים) ואחד ל-ZIP (חדש, מופיע רק לאחר הצלחת ה-PDF).
2. **סדר עיבוד**: PDF ראשון → שמירת `parentPn` ב-state → העלאת ZIP → קריאה ל-`/api/rafael-zip`.
3. **טבלה נפרדת**: PLR מוצג מתחת לטבלת RFQ הקיימת (עמודות: `#`, `Operation Sequence`, `Component Item`).
4. **שגיאה מבודדת**: כשל ב-ZIP מציג badge שגיאה ליד ה-Dropzone של ZIP בלבד; תוצאות ה-PDF לא מושפעות.

---

## תלויות Python חדשות

```
xlrd>=2.0.1   # binary CDFV2 .xls via pandas
```

מוסיף ל-`requirements.txt`; מותקן ב-Vercel/worker בעת הבנייה.
