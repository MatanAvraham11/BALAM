"use client";

import { useState } from "react";

type Props = {
  title: string;
  description?: string;
  locked?: boolean;
  onEnter?: () => void;
};

function LockIcon({ className }: { className?: string }) {
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
      <rect x="5" y="11" width="14" height="10" rx="2" />
      <path d="M8 11V7a4 4 0 0 1 8 0v4" />
    </svg>
  );
}

export default function ProductCard({
  title,
  description,
  locked,
  onEnter,
}: Props) {
  const [expanded, setExpanded] = useState(false);

  if (locked) {
    return (
      <div className="relative flex flex-col items-center justify-center gap-3 rounded-xl border border-gray-200 bg-white/60 p-6 text-center shadow-sm backdrop-blur-sm select-none">
        <LockIcon className="h-8 w-8 text-gray-300" />
        <h3 className="text-base font-bold text-nativ-dark/50">{title}</h3>
        <span className="rounded-full bg-gray-100 px-3 py-1 text-xs font-semibold text-gray-400">
          בפיתוח
        </span>
      </div>
    );
  }

  return (
    <div
      onClick={() => setExpanded((v) => !v)}
      className="flex cursor-pointer flex-col gap-3 rounded-xl border border-gray-200 bg-white p-6 shadow-sm transition-all hover:shadow-md hover:border-nativ-gold/40"
    >
      <h3 className="text-lg font-bold text-nativ-dark">{title}</h3>

      {expanded && (
        <>
          <p className="text-sm leading-relaxed text-nativ-dark/70">
            {description}
          </p>
          <button
            onClick={(e) => {
              e.stopPropagation();
              onEnter?.();
            }}
            className="mt-1 w-full rounded-lg bg-nativ-gold px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-nativ-gold-hover"
          >
            כניסה למוצר
          </button>
        </>
      )}
    </div>
  );
}
