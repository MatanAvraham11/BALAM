import Link from "next/link";
import Image from "next/image";

type SiteNavProps = {
  /** When set (e.g. product view on home), clicking the brand returns to the dashboard instead of navigating away */
  onBrandClick?: () => void;
};

export default function SiteNav({ onBrandClick }: SiteNavProps) {
  const brandClassName =
    "flex shrink-0 items-start gap-3 outline-none transition-opacity hover:opacity-90 focus-visible:rounded-md focus-visible:ring-2 focus-visible:ring-nativ-gold/40 focus-visible:ring-offset-2";

  const brandInner = (
    <>
      <Image
        src="/branding/nativ-logo.svg"
        alt="Nativ"
        width={96}
        height={44}
        unoptimized
        draggable={false}
        className="h-10 w-auto shrink-0 self-start object-contain sm:h-11"
      />
      <div className="flex min-w-0 flex-col items-start gap-0.5 pt-0.5 sm:pt-1">
        <span className="font-semibold leading-tight text-nativ-dark">
          נתיב מערכות
        </span>
        <span className="max-w-[12rem] text-xs leading-snug text-nativ-dark/70 sm:max-w-none sm:text-sm">
          מערכות ואוטומציות למפעלים
        </span>
      </div>
    </>
  );

  return (
    <header className="sticky top-0 z-50 w-full border-b border-stone-200/90 bg-white/90 backdrop-blur-md">
      <nav className="mx-auto flex w-full max-w-7xl flex-wrap items-center justify-between gap-4 px-4 py-4 sm:px-6 lg:px-8">
        {onBrandClick ? (
          <button
            type="button"
            onClick={onBrandClick}
            className={brandClassName}
            aria-label="חזרה לדשבורד"
          >
            {brandInner}
          </button>
        ) : (
          <Link
            href="/"
            prefetch={false}
            className={brandClassName}
          >
            {brandInner}
          </Link>
        )}

        <div className="flex flex-wrap items-center justify-end gap-1 sm:gap-2">
          <Link
            href="/about"
            className="rounded-md px-3 py-2 text-sm font-medium text-nativ-dark/90 transition-colors hover:bg-stone-100 hover:text-nativ-dark"
          >
            אודות
          </Link>
          <Link
            href="/pricing"
            className="rounded-md px-3 py-2 text-sm font-medium text-nativ-dark/90 transition-colors hover:bg-stone-100 hover:text-nativ-dark"
          >
            תמחור
          </Link>
          <Link
            href="/faq"
            className="rounded-md px-3 py-2 text-sm font-medium text-nativ-dark/90 transition-colors hover:bg-stone-100 hover:text-nativ-dark"
          >
            שאלות נפוצות
          </Link>
          <Link
            href="/support"
            className="rounded-md px-3 py-2 text-sm font-medium text-nativ-dark/90 transition-colors hover:bg-stone-100 hover:text-nativ-dark"
          >
            מרכז עזרה
          </Link>
          <Link
            href="/contact"
            className="mr-1 rounded-md bg-nativ-gold px-4 py-2 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-nativ-gold-hover"
          >
            צור קשר
          </Link>
        </div>
      </nav>
    </header>
  );
}
