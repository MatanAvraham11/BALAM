import type { Metadata } from "next";
import ContactForm from "../../components/ContactForm";

export const metadata: Metadata = {
  title: "צור קשר | נתיב מערכות",
  description: "השאירו פרטים ונחזור אליכם לבחינת הצורך והתאמת המוצר",
};

export default function ContactPage() {
  return (
    <div>
      <h1 className="text-2xl font-bold tracking-tight text-nativ-dark sm:text-3xl">צור קשר</h1>
      <p className="mt-4 leading-relaxed text-nativ-dark/90">
        השאירו פרטים ונחזור אליכם לבחינת הצורך, התאמת המוצר הרלוונטי והצגת תהליך עבודה מתאים.
      </p>
      <div className="mt-10">
        <ContactForm />
      </div>
    </div>
  );
}
