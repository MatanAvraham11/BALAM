import type { Metadata } from "next";
import SiteNav from "../components/SiteNav";

export const metadata: Metadata = {
  title: "נתיב מערכות | אתר",
  description: "מערכות ואוטומציות למפעלי ייצור",
};

export default function MarketingLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <div className="flex min-h-screen flex-col">
      <SiteNav />
      <main className="mx-auto w-full max-w-4xl flex-1 px-4 py-10 sm:px-6 lg:px-8 lg:py-14">
        {children}
      </main>
      <footer className="border-t border-stone-200 bg-white/80 py-6 text-center text-sm text-nativ-dark/60">
        נתיב מערכות בע״מ · Nativ Systems Ltd.
      </footer>
    </div>
  );
}
