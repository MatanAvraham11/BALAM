import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "תמחור | נתיב מערכות",
  description: "תמחור מותאם לסוגי מוצרים, משתמשים והתאמה לתהליכי העבודה",
};

export default function PricingPage() {
  return (
    <article className="max-w-none text-nativ-dark">
      <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">תמחור</h1>
      <p className="mt-6 leading-relaxed text-nativ-dark/90">
        המערכת מתומחרת בהתאם לסוגי המוצרים הנדרשים, מספר המשתמשים, היקף השימוש ורמת ההתאמה הנדרשת
        לתהליכי העבודה של החברה. השאירו פרטים ונחזור אליכם עם מודל עבודה והצעת מחיר מותאמת.
      </p>
      <div className="mt-10">
        <Link
          href="/contact#quote"
          className="inline-flex items-center justify-center rounded-md bg-nativ-gold px-6 py-3 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-nativ-gold-hover"
        >
          בקשת הצעת מחיר
        </Link>
      </div>
    </article>
  );
}
