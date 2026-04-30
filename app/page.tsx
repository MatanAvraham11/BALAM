"use client";

import { useState } from "react";
import ProductCard from "./components/ProductCard";
import BalamTab from "./components/BalamTab";
import DrawingTab from "./components/DrawingTab";

type ActiveView = "dashboard" | "balam" | "drawing";

const PRODUCTS = [
  {
    id: "balam" as const,
    title: "מיפוי בל״מ מלא",
    description:
      "ממיר אוטומטית בל״מ ארוך ומסורבל ב PDF לטבלת CSV מסודרת ונגישה. רלוונטי לעבודה מול חברות גדולות והזנת נתונים ל-ERP בצורה מהירה.",
  },
  {
    id: "drawing" as const,
    title: "מיפוי שרטוטים מלא",
    description:
      "מחלץ מידות מלקט שרטוטים, יוצר טבלת CSV ומוסיף בלונים ממוספרים. חיבור ישיר לרצפת ייצור ללא עיבוד ידני וטעויות.",
  },
];

const LOCKED = [
  { title: "מחיקת וניקוי מיתוג" },
  { title: "התאמת מיתוג (White Label)" },
  { title: "הפקת פקודות ייצור אוטומטית" },
  { title: "אימות נתונים ושרטוטים אוטומטי" },
];

function BackArrow({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="2"
    >
      <path d="M19 12H5M12 19l7-7-7-7" />
    </svg>
  );
}

export default function Home() {
  const [view, setView] = useState<ActiveView>("dashboard");

  return (
    <div className="flex min-h-screen flex-col items-center">
      <header className="mx-auto w-full max-w-4xl px-4 pt-10 pb-4 text-center">
        <h1
          className="text-4xl font-extrabold tracking-tight text-nativ-dark cursor-pointer"
          onClick={() => setView("dashboard")}
        >
          Nativ
          <span className="mx-2 text-nativ-gold">|</span>
          <span className="text-nativ-gold">נתיב</span>
        </h1>
        <p className="mt-2 text-sm text-nativ-dark/70">
          חילוץ נתונים חכם ממסמכי רכש ושרטוטים הנדסיים
        </p>
      </header>

      <hr className="w-full max-w-4xl border-t border-gray-200" />

      <main className="mx-auto w-full max-w-5xl px-4 pt-6 pb-16">
        {view === "dashboard" && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {PRODUCTS.map((p) => (
              <ProductCard
                key={p.id}
                title={p.title}
                description={p.description}
                onEnter={() => setView(p.id)}
              />
            ))}
            {LOCKED.map((p) => (
              <ProductCard key={p.title} title={p.title} locked />
            ))}
          </div>
        )}

        {view !== "dashboard" && (
          <div className="flex flex-col gap-4">
            <button
              onClick={() => setView("dashboard")}
              className="flex items-center gap-1.5 self-start text-sm font-semibold text-nativ-gold transition-colors hover:text-nativ-gold-hover"
            >
              <BackArrow className="h-4 w-4" />
              חזרה לדשבורד
            </button>

            {view === "balam" && <BalamTab />}
            {view === "drawing" && <DrawingTab />}
          </div>
        )}
      </main>
    </div>
  );
}
