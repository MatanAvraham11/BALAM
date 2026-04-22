"use client";

import { useState, type ReactNode } from "react";

export type Tab = {
  id: string;
  label: string;
  content: ReactNode;
};

export default function Tabs({ tabs }: { tabs: Tab[] }) {
  const [active, setActive] = useState(tabs[0]?.id);

  return (
    <div className="w-full">
      <div className="flex gap-2 border-b border-gray-200 mb-6" dir="rtl">
        {tabs.map((t) => {
          const isActive = t.id === active;
          return (
            <button
              key={t.id}
              onClick={() => setActive(t.id)}
              className={`px-5 py-2 font-semibold text-sm transition-colors border-b-2 -mb-px ${
                isActive
                  ? "text-primary border-primary"
                  : "text-gray-600 border-transparent hover:text-gray-900"
              }`}
            >
              {t.label}
            </button>
          );
        })}
      </div>

      <div>
        {tabs.map((t) => (
          <div key={t.id} hidden={t.id !== active}>
            {t.content}
          </div>
        ))}
      </div>
    </div>
  );
}
