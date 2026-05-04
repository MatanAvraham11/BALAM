"use client";

type Props = {
  title: string;
  description?: string;
  locked?: boolean;
  onEnter?: () => void;
};

/** Same height as primary CTA row so locked cards align with unlocked footers */
const FOOTER_ROW_CLASS = "flex min-h-[44px] w-full shrink-0 items-center justify-center";

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
  if (locked) {
    return (
      <div className="flex h-full min-h-[280px] select-none flex-col rounded-xl border border-gray-200 bg-white/60 p-6 text-right shadow-sm backdrop-blur-sm">
        <div className="flex shrink-0 items-start gap-2">
          <LockIcon
            className="mt-0.5 h-5 w-5 shrink-0 text-gray-400"
          />
          <h3 className="min-w-0 flex-1 text-lg font-bold text-nativ-dark/55">
            {title}
          </h3>
        </div>
        {description ? (
          <p className="mt-3 min-h-0 flex-1 text-sm leading-relaxed text-nativ-dark/55">
            {description}
          </p>
        ) : (
          <div className="flex min-h-0 flex-1 flex-col items-center justify-center py-4">
            <LockIcon className="h-8 w-8 text-gray-300" />
          </div>
        )}
        <div className={FOOTER_ROW_CLASS}>
          <span className="rounded-full bg-gray-100 px-3 py-1.5 text-xs font-semibold text-gray-400">
            בפיתוח
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-[280px] flex-col rounded-xl border border-gray-200 bg-white p-6 shadow-sm transition-shadow hover:border-nativ-gold/40 hover:shadow-md">
      <h3 className="shrink-0 text-lg font-bold text-nativ-dark">{title}</h3>
      <p className="mt-3 min-h-0 flex-1 text-sm leading-relaxed text-nativ-dark/70">
        {description}
      </p>
      <div className={FOOTER_ROW_CLASS}>
        <button
          type="button"
          onClick={() => onEnter?.()}
          className="w-full rounded-lg bg-nativ-gold px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-nativ-gold-hover"
        >
          כניסה למוצר
        </button>
      </div>
    </div>
  );
}
