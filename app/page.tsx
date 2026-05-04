"use client";

import { useState } from "react";
import SiteNav from "./components/SiteNav";
import LogoMarquee from "./components/LogoMarquee";
import ProductCard from "./components/ProductCard";
import BalamTab from "./components/BalamTab";
import DrawingTab from "./components/DrawingTab";

type ActiveView = "dashboard" | "balam" | "drawing";

const PRODUCTS = [
  {
    id: "balam" as const,
    title: "מיפוי בל״מ מלא",
    description:
      "חילוץ, המרה וסידור של נתונים מתוך בל״מ לקובץ CSV במטרה לאפשר עבודה על נתונים מסודרים, הזנה מהירה למערכות, וצמצום עבודה ידנית.",
  },
  {
    id: "drawing" as const,
    title: "מיפוי שרטוטים מלא",
    description:
      "חילוץ, המרה וסימון של מידות מתוך שרטוטים כולל יצירת בלונים וטבלאות במטרה לאפשר חיבור בין שרטוט לנתונים, הזנה ישירה ל-ERP, והפעלת ייצור ללא עיבוד ידני.",
  },
];

const LOCKED = [
  {
    title: "מחיקת וניקוי מיתוג",
    description:
      "זיהוי, מחיקה וניקוי של מיתוג, טקסטים ו-Metadata מקבצים במטרה לאפשר העברת קבצים ללא חשיפת מקור, עבודה מול צד שלישי, ושמירה על סיווג.",
  },
  {
    title: "התאמת מיתוג",
    description:
      "מחיקה, החלפה והטמעה של מיתוג חדש בקבצים לפי דרישת לקוח במטרה לאפשר עבודה תחת מותג לקוח, ייצור דרך צד שלישי, והפעלה של White Label.",
  },
  {
    title: "הפקת פקודות ייצור אוטומטית",
    description:
      "המרה, חלוקה ויצירה של פקודות עבודה מתוך נתונים ושרטוטים במטרה לאפשר תכנון משימות, הגדרת כמויות, וביצוע ייצור מסודר.",
  },
  {
    title: "אימות נתונים ושרטוטים אוטומטי",
    description:
      "הצלבה, בדיקה וזיהוי חריגות בין CSV, שרטוטים ובלונים במטרה לאפשר איתור טעויות לפני ייצור, מניעת עבודה חוזרת, ושמירה על מקור אמת אחד.",
  },
  {
    title: "דיווח ייצור בנייד",
    description:
      "הזנה, עדכון וריכוז של נתונים בזמן אמת מריצפת הייצור. במטרה לאפשר מעקב, בקרה על כמויות וזמנים, וזיהוי עיכובים מידי.",
  },
  {
    title: "אוטומציית מכרזים (בל״מים)",
    description:
      "חילוץ, ניתוח והמרה של נתונים מתוך בל״מ במטרה לאפשר הכנת הצעות מחיר מהירה, עבודה על נתונים מסודרים, וצמצום טעויות ופספוסים.",
  },
  {
    title: "דאטה בייס ספקי ציפויים",
    description:
      "ניתוח, זיהוי והתאמת ספקים לציפויים מתוך שרטוטים במטרה לאפשר איתור ספקים רלוונטיים, שליחת בקשות להצעת מחיר, ובחירה מדויקת של ספק.",
  },
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
    <div className="flex min-h-screen w-full flex-col">
      <SiteNav />

      <main className="mx-auto w-full max-w-7xl px-4 pb-16 pt-4 sm:px-6 lg:px-8">
        {view === "dashboard" && (
          <>
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
                  <ProductCard
                    title={p.title}
                    description={p.description}
                    locked
                  />
                </div>
              ))}
            </div>
            <LogoMarquee />
          </>
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
