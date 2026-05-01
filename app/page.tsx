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

  function goHome() {
    setView("dashboard");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  return (
    <div className="flex min-h-screen flex-col items-center">
      <header className="w-full border-b border-gray-200 bg-white/60">
        <div className="mx-auto flex w-full max-w-7xl items-center justify-between px-4 py-6 sm:px-6 lg:px-8">
          <button
            type="button"
            dir="ltr"
            onClick={goHome}
            aria-label='Nativ נתיב — חזרה לעמוד הבית'
            className="flex w-full cursor-pointer items-center justify-between gap-4 text-start outline-none transition-colors hover:opacity-90 focus-visible:rounded-md focus-visible:ring-2 focus-visible:ring-nativ-gold/50 focus-visible:ring-offset-2 focus-visible:ring-offset-white/60"
          >
            <img
              src="/branding/nativ-logo.svg"
              alt="Nativ Logo"
              draggable={false}
              fetchPriority="high"
              className="pointer-events-none h-12 w-auto shrink-0 object-contain object-left sm:h-14"
            />
            <div dir="rtl" className="min-w-0 shrink pl-2 text-right sm:pl-4">
              <h1 className="text-xl font-extrabold leading-tight tracking-tight text-nativ-dark sm:text-2xl">
                Nativ
                <span className="mx-1.5 text-nativ-gold sm:mx-2">|</span>
                <span className="text-nativ-gold">נתיב</span>
              </h1>
              <p className="mt-0.5 max-w-md text-xs leading-snug text-nativ-dark/70 sm:text-sm">
                מערכות ואוטומציות למפעלים
              </p>
            </div>
          </button>
        </div>
      </header>

      <main className="mx-auto w-full max-w-7xl px-4 pb-16 pt-4 sm:px-6 lg:px-8">
        {view === "dashboard" && (
          <div className="grid grid-cols-1 items-stretch gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {PRODUCTS.map((p) => (
              <div key={p.id} className="h-full min-h-0">
                <ProductCard
                  title={p.title}
                  description={p.description}
                  onEnter={() => setView(p.id)}
                />
              </div>
            ))}
            {LOCKED.map((p) => (
              <div key={p.title} className="h-full min-h-0">
                <ProductCard title={p.title} locked />
              </div>
            ))}
          </div>
        )}

        {view !== "dashboard" && (
          <div className="flex flex-col gap-4">
            <button
              onClick={goHome}
              type="button"
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
