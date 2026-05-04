"use client";

const PARTNERS = [
  { src: "/branding/partners/yaaf.svg", alt: "YAAF" },
  { src: "/branding/partners/uptimum.svg", alt: "Uptimum" },
  { src: "/branding/partners/meital-group.svg", alt: "Meital Group" },
  { src: "/branding/partners/manufuture.svg", alt: "ManuFuture" },
] as const;

function LogoRow() {
  return (
    <>
      {PARTNERS.map(({ src, alt }) => (
        <div
          key={src}
          className="flex shrink-0 items-center justify-center"
        >
          <img
            src={src}
            alt={alt}
            loading="lazy"
            decoding="async"
            draggable={false}
            className="h-[3.75rem] w-auto max-w-[13.5rem] object-contain object-center mix-blend-multiply grayscale transition-[filter,opacity] duration-300 ease-out hover:grayscale-0 sm:h-[4.5rem] md:h-[5.25rem] lg:h-24 sm:max-w-[16.5rem] md:max-w-none"
          />
        </div>
      ))}
    </>
  );
}

/** אחת משתי הכפילויות ללולאה; מרווח קבוע אחרי השורה כדי שלא ייצמדו לוגו↔לוגו במפר הלולאה */
function LogoTrack({ duplicate }: { duplicate?: boolean }) {
  return (
    <div
      className="flex shrink-0 items-center gap-16 sm:gap-24 md:gap-32 lg:gap-40"
      aria-hidden={duplicate ? true : undefined}
    >
      <LogoRow />
      <div
        className="h-1 w-8 shrink-0 sm:w-10 md:w-12 lg:w-14"
        aria-hidden
      />
    </div>
  );
}

export default function LogoMarquee() {
  return (
    <section
      className="mt-12 w-full border-t border-stone-200/80 pt-10 sm:mt-14 sm:pt-12"
      aria-labelledby="partners-marquee-heading"
    >
      <h2
        id="partners-marquee-heading"
        className="mb-8 text-center text-xl font-semibold tracking-tight text-nativ-dark sm:mb-10 sm:text-2xl md:text-3xl"
      >
        <span className="bg-gradient-to-l from-nativ-gold/90 to-nativ-gold bg-clip-text text-transparent">
          כבר משתמשים במוצרים שלנו
        </span>
      </h2>

      {/* full-bleed: margin-inline מתאים גם ל־RTL (לא כמו left-1/2 + translate שפותחים פער בצד אחד) */}
      <div
        className="relative w-[100vw] max-w-[100vw] shrink-0 ms-[calc(50%-50vw)] me-[calc(50%-50vw)]"
        dir="ltr"
      >
        <div className="relative overflow-hidden bg-gray-50 py-7 sm:py-9 md:py-10">
          {/* Fade מקצוות — תואם ל־bg-gray-50 של הפס */}
          <div
            className="pointer-events-none absolute inset-y-0 left-0 z-10 w-20 bg-gradient-to-r from-gray-50 from-[12%] via-gray-50/65 to-transparent sm:w-28 md:w-40 md:from-[8%]"
            aria-hidden
          />
          <div
            className="pointer-events-none absolute inset-y-0 right-0 z-10 w-20 bg-gradient-to-l from-gray-50 from-[12%] via-gray-50/65 to-transparent sm:w-28 md:w-40 md:from-[8%]"
            aria-hidden
          />

          <div className="flex w-max animate-logo-marquee">
            <LogoTrack />
            <LogoTrack duplicate />
          </div>
        </div>
      </div>
    </section>
  );
}
