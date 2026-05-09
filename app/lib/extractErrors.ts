/**
 * When upload processing fails for reasons other than explicit client validation,
 * append guidance to verify the file contains the expected data (בל״מ / שרטוט).
 * Do not use this for dropzone rejection messages (wrong type, size, count).
 */
export function appendDataCheckHint(
  message: string | undefined,
  product: "balam" | "drawing",
): string {
  const base =
    message?.trim() ||
    (product === "balam"
      ? "לא ניתן לחלץ נתונים מהקובץ."
      : "לא ניתן לנתח את השרטוט.");
  const hint =
    product === "balam"
      ? "נא לבדוק שהקובץ הוא בל״מ תקין ושהנתונים הנדרשים (פריטים, כמויות וכו׳) מופיעים בו."
      : "נא לבדוק שהקובץ הוא PDF שרטוט תקין ושמופיעות בו המידות והפרטים הנדרשים.";
  return `${base} ${hint}`;
}
