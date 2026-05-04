import type { Metadata } from "next";
import { Heebo } from "next/font/google";
import SiteFooter from "./components/SiteFooter";
import "./globals.css";

const heebo = Heebo({
  variable: "--font-heebo",
  subsets: ["latin", "hebrew"],
});

export const metadata: Metadata = {
  title: "נתיב | Nativ",
  description: "מערכות ואוטומציות למפעלים",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="he" dir="rtl" className={`${heebo.variable} h-full antialiased`}>
      <body className="flex min-h-screen flex-col font-sans bg-nativ-light text-nativ-dark">
        <div className="flex min-h-0 flex-1 flex-col">{children}</div>
        <SiteFooter />
      </body>
    </html>
  );
}
