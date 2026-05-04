import Link from "next/link";

const FOOTER_LINKS = [
  { href: "/", label: "בית" },
  { href: "/about", label: "אודות" },
  { href: "/pricing", label: "תמחור" },
  { href: "/faq", label: "שאלות נפוצות" },
  { href: "/support", label: "מרכז עזרה" },
  { href: "/contact", label: "צור קשר" },
] as const;

export default function SiteFooter() {
  return (
    <footer className="mt-auto w-full border-t border-stone-200 bg-white/90 backdrop-blur-sm">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-8 px-4 py-10 sm:px-6 lg:px-8">
        <div className="flex flex-col gap-6 sm:flex-row sm:items-start sm:justify-between">
          <div className="max-w-md text-right">
            <p className="text-base font-semibold text-nativ-dark">נתיב מערכות</p>
            <p className="mt-1 text-sm leading-relaxed text-nativ-dark/70">
              מערכות ואוטומציות למפעלי ייצור — פשוטות, מדויקות ומחוברות לתהליך שלכם.
            </p>
          </div>
          <nav
            className="flex flex-wrap items-center justify-start gap-x-5 gap-y-2 sm:justify-end"
            aria-label="קישורי תחתית"
          >
            {FOOTER_LINKS.map(({ href, label }) => (
              <Link
                key={href}
                href={href}
                className="text-sm font-medium text-nativ-dark/85 transition-colors hover:text-nativ-gold"
              >
                {label}
              </Link>
            ))}
          </nav>
        </div>
        <div className="flex flex-col gap-2 border-t border-stone-200/80 pt-6 text-right text-xs text-nativ-dark/55 sm:flex-row sm:items-center sm:justify-between">
          <span>© {new Date().getFullYear()} נתיב מערכות בע״מ · Nativ Systems Ltd.</span>
          <span className="text-nativ-dark/45">כל הזכויות שמורות.</span>
        </div>
      </div>
    </footer>
  );
}
