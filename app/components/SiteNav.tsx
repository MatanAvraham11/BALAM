import Link from "next/link";

export default function SiteNav() {
  return (
    <header className="sticky top-0 z-50 border-b border-stone-200/90 bg-white/90 backdrop-blur-md">
      <nav className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-4 py-4 sm:px-6 lg:px-8">
        <Link
          href="/"
          className="flex shrink-0 items-center gap-3 outline-none transition-opacity hover:opacity-90 focus-visible:rounded-md focus-visible:ring-2 focus-visible:ring-nativ-gold/40 focus-visible:ring-offset-2"
        >
          <img
            src="/branding/nativ-logo.svg"
            alt="Nativ"
            draggable={false}
            className="h-10 w-auto object-contain sm:h-11"
          />
          <span className="hidden font-semibold text-nativ-dark sm:inline">
            נתיב מערכות
          </span>
        </Link>

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
