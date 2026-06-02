# Rafael PLR / ZIP — Phase 2 (V.6.1)

מסמך זה מתאר את מבנה ה-ZIP הנתמך, פענוח קבצי ה-XLS, עמודות הפלט, וקודי השגיאה.

---

## מבנה ZIP מצופה

```
TransferRequest_*.zip          ← עטיפה חיצונית (אופציונלי)
└── <id>_1_PRODUCT.ZIP         ← ה-ZIP האמיתי
    └── data/files/            ← אותיות קטנות
        ├── PLReport_<PN>_*.zip  ← כל PLR הוא ZIP מקונן
        │   └── *.xls            ← קובץ XLS בינארי אחד או יותר
        ├── *_MLEDR Report_*.xls   ← מתעלמים (לא נפרס)
        └── *.pdf / *.stp / …
```

### כללים לניתוב
- אם ה-ZIP שהועלה מכיל חבר **יחיד** שמסתיים ב-`_PRODUCT.ZIP` — נכנסים לתוכו.
- אחרת מניחים שה-ZIP שהועלה הוא עצמו ה-Product ZIP.
- מתחת ל-`data/files/` נבחרים **רק** קבצים עם סיומת `.zip` ששם הקובץ מתחיל ב-`PLReport` (לא רגיש לרישיות).
- קבצי `.xls` / `.csv` **שטוחים** ישירות ב-`data/files/` — **לא** נפרסים.
- כל ZIP מקונן נפתח בזיכרון; כל קובץ `.xls` שבתוכו נפרס.
- אם ZIP מקונן מסוג `PLReport*.zip` לא מכיל אפילו קובץ `.xls` אחד — זו שגיאה.
- שורות נתונים עם עמודה ריקה מובילה (למשל `,1.0,,316150321,...`) נתמכות — האינדקסים נקבעים לפי שורת ה-header.

---

## פענוח PLR

הפענוח הוא XLS בלבד:

`pandas.read_excel(..., engine="xlrd", header=None, dtype=str)`.

הפרסר מאתר שורת `Part List for: <PN>` ואז את טבלת הנתונים לפי header שמכיל את שלוש העמודות:
`Operation Sequence`, `Component Item`, `QTY`.

---

## עמודות תוצאה

| שדה               | תיאור                                   |
|-------------------|-----------------------------------------|
| `operation_sequence` | שדה "Operation Sequence" מה-PLR.    |
| `component_item`  | שדה "Component Item" מה-PLR.           |
| `qty`             | שדה "QTY" מה-PLR.                      |

### מטא-נתונים בפלט

| שדה                  | תיאור                                                                   |
|----------------------|-------------------------------------------------------------------------|
| `matched_file_count` | כמה קבצי XLS שה-PN שלהם == `parent_part_number` (שורותיהם בראש הרשימה). |
| `plreport_zip_count` | סה״כ קבצי `PLReport*.zip` שנמצאו.                                       |
| `xls_file_count`     | סה״כ קבצי XLS שנפרסו מתוך קבצי ה-PLReport.                              |
| `txt_base64`         | קובץ PLR TXT מקודד base64 אחרי encoding ל-`windows-1255`.               |
| `txt_filename`       | שם קובץ ה-TXT להורדה.                                                   |

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
| אין `data/files/PLReport*.zip` בתוך ה-ZIP | 400  | `{"detail": "לא נמצאו קבצי PLReport*.zip בתוך data/files/."}`                      |
| `PLReport*.zip` ללא XLS                  | 400  | `{"detail": "<filename>: לא נמצא קובץ XLS בתוך ה-PLReport."}`                      |
| קובץ XLS ללא שורת `Part List for:`       | 400  | `{"detail": "<filename>: לא נמצאה שורת Part List …"}`                              |
| קובץ XLS ללא header נדרש                 | 400  | `{"detail": "<filename>: לא נמצאה טבלת PLR עם העמודות …"}`                         |
| קובץ XLS ללא שורות נתונים                | 400  | `{"detail": "<filename>: לא נמצאו שורות נתונים …"}`                                |
| ZIP פנימי מקונן פגום                     | 400  | `{"detail": "<filename>: הזיפ המקונן פגום …"}`                                     |
| ZIP גדול מ-50 MB                         | 400  | `{"detail": "ZIP גדול מדי (N MB); המקסימום הוא 50 MB."}`                          |
| auth נדחה                                | 401  | `{"detail": "Unauthorized"}`                                                         |

---

## אינטגרציה בצד הלקוח

1. **Dropzone אחד**: אותו אזור העלאה מקבל PDF ו-ZIP ביחד או אחד-אחד.
2. **סדר עיבוד**: PDF ראשון → שמירת `parentPn` → ZIP → קריאה ל-`/api/rafael-zip`.
3. **טבלה נפרדת**: PLR מוצג מתחת לטבלת RFQ הקיימת (עמודות: `Operation Sequence`, `Component Item`, `QTY`).
4. **ייצוא**: PLR יורד כ-TXT מופרד בטאבים, מקודד `windows-1255`.
5. **שגיאה מבודדת**: כשל ב-ZIP מוצג באזור ה-PLR; תוצאות ה-PDF לא נמחקות.

---

## תלויות Python חדשות

```
xlrd>=2.0.1   # binary CDFV2 .xls via pandas
```

מוסיף ל-`requirements.txt`; מותקן ב-Vercel/worker בעת הבנייה.
