"use client";

import { useEffect, useState } from "react";

const DRAWING_STATUSES = [
  "מעלה קובץ סרוק...",
  "מנתח גיאומטריה ומזהה עוגנים...",
  "מחשב מיקומי בלונים ומחלץ מידות...",
  "מפיק טבלת נתונים...",
];

const BALAM_STATUSES = [
  "מעלה קובץ בל״מ...",
  "מנתח נתוני רכש...",
  "מזהה פריטים וכמויות...",
  "מפיק טבלת הזמנה...",
];

const RAFAEL_STATUSES = [
  "מעלה קובץ RFQ של רפאל...",
  "מזהה גלובלים (מספר בלם, קניין, תאריך הגשה)...",
  "מאתר מק״טים וכמויות לפי עמודות...",
  "מפצל לוחות אספקה לשורות נפרדות...",
  "מפיק קובץ TXT מופרד טאבים...",
];

type Props = {
  variant?: "drawing" | "balam" | "rafael";
};

export default function ProcessingStatus({ variant = "drawing" }: Props) {
  const statuses =
    variant === "balam"
      ? BALAM_STATUSES
      : variant === "rafael"
        ? RAFAEL_STATUSES
        : DRAWING_STATUSES;

  return <ProcessingStatusTicker key={variant} statuses={statuses} />;
}

function ProcessingStatusTicker({ statuses }: { statuses: readonly string[] }) {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setIndex((current) => (current + 1) % statuses.length);
    }, 1500);

    return () => window.clearInterval(timer);
  }, [statuses.length]);

  return (
    <div className="rounded-lg border border-nativ-gold/20 bg-nativ-gold/5 px-4 py-3 text-sm font-semibold text-nativ-dark/80">
      {statuses[index]}
    </div>
  );
}
