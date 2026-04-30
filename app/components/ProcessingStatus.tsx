"use client";

import { useEffect, useState } from "react";

const STATUSES = [
  "מעלה קובץ סרוק...",
  "מנתח גיאומטריה ומזהה עוגנים...",
  "מחשב מיקומי בלונים ומחלץ מידות...",
  "מפיק טבלת נתונים...",
];

export default function ProcessingStatus() {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setIndex((current) => (current + 1) % STATUSES.length);
    }, 1500);

    return () => window.clearInterval(timer);
  }, []);

  return (
    <div className="rounded-lg border border-nativ-gold/20 bg-nativ-gold/5 px-4 py-3 text-sm font-semibold text-nativ-dark/80">
      {STATUSES[index]}
    </div>
  );
}
