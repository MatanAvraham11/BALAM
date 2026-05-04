"use client";

type Props = {
  title: string;
  description?: string;
  /** נתיב לאייקון SVG תחת /public */
  iconSrc: string;
  locked?: boolean;
  /** When locked: תג תחתון לפי סוג מוצר */
  lockedStatus?: "development" | "not_in_package";
  onEnter?: () => void;
};

/** Same height as primary CTA row so locked cards align with unlocked footers */
const FOOTER_ROW_CLASS =
  "flex min-h-[44px] w-full shrink-0 items-center justify-center";

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

function CardIcon({
  iconSrc,
  title,
  locked,
}: {
  iconSrc: string;
  title: string;
  locked: boolean;
}) {
  return (
    <div className="flex shrink-0 items-start gap-3">
      <div className="relative shrink-0">
        <div
          className={
            locked
              ? "flex h-[3.25rem] w-[3.25rem] items-center justify-center rounded-2xl border border-stone-200/90 bg-stone-50/90 sm:h-14 sm:w-14"
              : "flex h-[3.25rem] w-[3.25rem] items-center justify-center rounded-2xl border border-nativ-gold/20 bg-gradient-to-br from-white to-amber-50/40 shadow-sm ring-1 ring-nativ-gold/10 sm:h-14 sm:w-14"
          }
        >
          <img
            src={iconSrc}
            alt=""
            width={48}
            height={48}
            draggable={false}
            className="h-9 w-9 object-contain sm:h-10 sm:w-10"
          />
        </div>
        {locked ? (
          <span
            className="absolute -bottom-0.5 -left-0.5 flex h-6 w-6 items-center justify-center rounded-full border border-stone-200 bg-white shadow-sm"
            title="נעול"
            aria-hidden
          >
            <LockIcon className="h-3.5 w-3.5 text-gray-400" />
          </span>
        ) : null}
      </div>
      <h3
        className={
          locked
            ? "min-w-0 flex-1 pt-0.5 text-lg font-bold leading-snug text-nativ-dark/55"
            : "min-w-0 flex-1 pt-0.5 text-lg font-bold leading-snug text-nativ-dark"
        }
      >
        {title}
      </h3>
    </div>
  );
}

export default function ProductCard({
  title,
  description,
  iconSrc,
  locked,
  lockedStatus = "development",
  onEnter,
}: Props) {
  if (locked) {
    const badgeText =
      lockedStatus === "not_in_package"
        ? "לא נכללים בחבילה שלך"
        : "בפיתוח";
    return (
      <div className="flex h-full min-h-[280px] select-none flex-col rounded-xl border border-gray-200 bg-white/60 p-6 text-right shadow-sm backdrop-blur-sm">
        <CardIcon iconSrc={iconSrc} title={title} locked />
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
          <span className="max-w-[min(100%,18rem)] rounded-full bg-gray-100 px-3 py-2 text-center text-[11px] font-semibold leading-snug text-gray-500 sm:text-xs">
            {badgeText}
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-[280px] flex-col rounded-xl border border-gray-200 bg-white p-6 shadow-sm transition-shadow hover:border-nativ-gold/40 hover:shadow-md">
      <CardIcon iconSrc={iconSrc} title={title} locked={false} />
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
