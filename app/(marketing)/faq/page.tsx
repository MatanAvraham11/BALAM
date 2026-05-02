import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "שאלות נפוצות | נתיב מערכות",
  description: "תשובות לשאלות נפוצות על המערכת, תמחור ותמיכה",
};

const FAQ_ITEMS: { q: string; a: string }[] = [
  {
    q: "איך המערכת מקבלת קבצים ואילו פורמטים נתמכים?",
    a: "המערכת מקבלת קבצים בהתאם לסוג המוצר והתהליך, לרבות PDF, CSV וקבצים תפעוליים נוספים לפי צורך.",
  },
  {
    q: "כמה מדויקת המערכת בזיהוי נתונים?",
    a: "המערכת נבנתה לעבודה ברמת דיוק גבוהה, עם אפשרות לבדיקה, עריכה ואישור של התוצרים לפני שימוש.",
  },
  {
    q: "כמה זמן לוקח לעבד בל״מ או סט שרטוטים?",
    a: "ברוב התהליכים התוצר מתקבל בתוך כ10-20 שניות, בהתאם להיקף הקבצים וסוג העיבוד.",
  },
  {
    q: "האם נדרשת הטמעה לפני תחילת עבודה?",
    a: "חלק מהמוצרים זמינים לשימוש מידי, וחלק דורשים התאמה קצרה לתהליך העבודה של החברה.",
  },
  {
    q: "האם המערכת מתחברת ל ERP?",
    a: "כן, ניתן לחבר את תוצרי המערכת למערכות ERP בהתאם למנוי, למבנה הנתונים ולצרכי הלקוח.",
  },
  {
    q: "האם ניתן לבדוק ולתקן את התוצרים לפני שימוש?",
    a: "כן, כל תוצר ניתן לבדיקה, עריכה ואישור לפני העברה לשימוש תפעולי.",
  },
  {
    q: "איך המערכת מזהה טעויות?",
    a: "המערכת מצליבה בין מקורות מידע שונים ומזהה חוסרים, כפילויות, חריגות ואי התאמות.",
  },
  {
    q: "האם המערכת מתאימה לפרויקטים גדולים?",
    a: "כן, המערכת מיועדת לעבודה עם נפחי מידע גדולים, תהליכים מורכבים ודרישות תפעוליות גבוהות.",
  },
  {
    q: "איך מתבצע התמחור?",
    a: "התמחור מבוסס על סוגי המוצרים, מספר ההרשאות, היקף השימוש ורמת ההתאמה הנדרשת.",
  },
  {
    q: "האם יש הדרכה ותמיכה?",
    a: "כן, אנו מספקים ליווי בתחילת העבודה ותמיכה שוטפת בהתאם לצורך.",
  },
  {
    q: "איך נשמרת אבטחת המידע?",
    a: "המערכת פועלת תחת עקרונות אבטחת מידע תעשייתיים. עיבוד הנתונים מתבצע בשרת מקומי, והקבצים אינם נשמרים או מועברים לצד שלישי.",
  },
  {
    q: "האם ניתן לבצע התאמות מיוחדות?",
    a: "כן, ניתן להתאים את המערכת לסוגי קבצים, תהליכי עבודה ודרישות עסקיות ספציפיות.",
  },
];

export default function FaqPage() {
  return (
    <div>
      <h1 className="text-2xl font-bold tracking-tight text-nativ-dark sm:text-3xl">שאלות נפוצות</h1>
      <div className="mt-8 space-y-3">
        {FAQ_ITEMS.map((item) => (
          <details
            key={item.q}
            className="group rounded-lg border border-stone-200 bg-white px-4 py-3 shadow-sm open:shadow-md"
          >
            <summary className="cursor-pointer list-none font-medium text-nativ-dark outline-none marker:content-none [&::-webkit-details-marker]:hidden">
              <span className="flex items-start justify-between gap-2">
                <span>{item.q}</span>
                <span className="shrink-0 text-nativ-gold transition-transform group-open:rotate-180">
                  ▼
                </span>
              </span>
            </summary>
            <p className="mt-3 border-t border-stone-100 pt-3 text-sm leading-relaxed text-nativ-dark/85">
              {item.a}
            </p>
          </details>
        ))}
      </div>
    </div>
  );
}
