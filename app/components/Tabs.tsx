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
      <div
        className="mb-6 flex gap-2 rounded-xl border border-gray-200 bg-white p-1 shadow-sm"
        dir="rtl"
      >
        {tabs.map((t) => {
          const isActive = t.id === active;
          return (
            <button
              key={t.id}
              onClick={() => setActive(t.id)}
              className={`flex-1 rounded-lg px-5 py-2.5 text-sm font-semibold transition-colors ${
                isActive
                  ? "bg-blue-600 text-white shadow-sm"
                  : "text-gray-600 hover:bg-blue-50 hover:text-blue-600"
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
