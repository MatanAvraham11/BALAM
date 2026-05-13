/**
 * When upload processing fails for reasons other than explicit client validation,
 * append guidance to verify the file contains the expected data (בל״מ / שרטוט / RFQ רפאל).
 * Do not use this for dropzone rejection messages (wrong type, size, count).
 */
export function appendDataCheckHint(
  message: string | undefined,
  product: "balam" | "drawing" | "rafael",
): string {
  const fallback: Record<typeof product, string> = {
    balam: "לא ניתן לחלץ נתונים מהקובץ.",
    drawing: "לא ניתן לנתח את השרטוט.",
    rafael: "לא ניתן לחלץ נתונים מקובץ ה-RFQ של רפאל.",
  };
  const hints: Record<typeof product, string> = {
    balam:
      "נא לבדוק שהקובץ הוא בל״מ תקין ושהנתונים הנדרשים (פריטים, כמויות וכו׳) מופיעים בו.",
    drawing:
      "נא לבדוק שהקובץ הוא PDF שרטוט תקין ושמופיעות בו המידות והפרטים הנדרשים.",
    rafael:
      "נא לבדוק שהקובץ הוא RFQ של רפאל ושמופיעים בו מספר בלם, מק״טים, כמויות ותאריכי אספקה.",
  };
  const base = message?.trim() || fallback[product];
  return `${base} ${hints[product]}`;
}
