import type { Metadata } from "next";
import LogoMarquee from "@/app/components/LogoMarquee";

export const metadata: Metadata = {
  title: "אודות | נתיב מערכות",
  description: "נתיב מערכות בע״מ — מערכות ואוטומציות למפעלי ייצור",
};

export default function AboutPage() {
  return (
    <>
      <article className="prose prose-stone max-w-none text-nativ-dark">
        <h1 className="text-2xl font-bold tracking-tight text-nativ-dark sm:text-3xl">
          נתיב מערכות בע״מ, Nativ Systems Ltd.
        </h1>
        <p className="mt-2 text-lg text-nativ-dark/80">מערכות ואוטומציות למפעלי ייצור.</p>
        <p className="mt-6 leading-relaxed text-nativ-dark/90">
          נתיב מערכות מפתחת פתרונות אוטומציה לחברות ייצור, עם התמחות בתהליכים מבוססי קבצים, שרטוטים, בל״מים
          ונתונים תפעוליים. המערכת מיועדת לחברות שעובדות עם תהליכים מורכבים, דרישות דיוק גבוהות ונפחי מידע
          גדולים. היתרון שלנו הוא התאמה של כל מוצר לתהליך העבודה בפועל של הלקוח, לצד ריכוז מספר אוטומציות
          תחת פלטפורמה אחת. כך ניתן לצמצם עבודה ידנית, להפחית טעויות, ולייצר תהליך עבודה ברור, מבוקר ויעיל
          יותר.
        </p>
      </article>
      <LogoMarquee />
    </>
  );
}
