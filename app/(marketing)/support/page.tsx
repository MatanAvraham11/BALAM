import type { Metadata } from "next";
import SupportForm from "../../components/SupportForm";

export const metadata: Metadata = {
  title: "מרכז תמיכה | נתיב מערכות",
  description: "פתיחת פנייה, דיווח על תקלה או בקשת סיוע",
};

export default function SupportPage() {
  return (
    <div>
      <h1 className="text-2xl font-bold tracking-tight text-nativ-dark sm:text-3xl">מרכז תמיכה</h1>
      <p className="mt-4 leading-relaxed text-nativ-dark/90">
        לפתיחת פנייה, דיווח על תקלה או בקשת סיוע, מלאו את הטופס ונחזור אליכם בהקדם.
      </p>
      <div className="mt-10">
        <SupportForm />
      </div>
    </div>
  );
}
