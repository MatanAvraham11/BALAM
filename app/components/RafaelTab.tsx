"use client";

import { useMemo, useState } from "react";
import FileDropzone from "./FileDropzone";
import InfoCard from "./InfoCard";
import DataTable from "./DataTable";
import ProcessingStatus from "./ProcessingStatus";
import { downloadBase64 } from "../lib/download";
import { appendDataCheckHint } from "../lib/extractErrors";

type RafaelRow = {
  "מספר שורה": number;
  "מספר בלם": string;
  "שם קניין": string;
  "תאריך סופי להגשה": string;
  "מקט רפאל": string;
  "כמות נדרשת": number;
  "זמן אספקה בשבועות": number;
  FAI: string;
};

type RafaelResponse = {
  rfq_number: string;
  buyer_name: string;
  submission_date: string;
  buyer_ocr_ready?: boolean;
  buyer_ocr_reason?: string | null;
  rows: RafaelRow[];
  txt_base64: string;
  txt_filename: string;
};

/** Human-readable Hebrew when the API returns the sentinel ``OCR Failed`` (infra / env). */
function rafaelBuyerDisplayLabel(
  buyerName: string,
  reason: string | null | undefined,
): string {
  if (buyerName !== "OCR Failed") {
    return buyerName.trim() ? buyerName : "—";
  }
  const byReason: Record<string, string> = {
    rafael_buyer_ocr_disabled:
      "OCR לשם הקניין כבוי (הסר את RAFAEL_BUYER_OCR או הגדר לערך חיובי)",
    tesseract_not_on_path: "חסר Tesseract בשרת — אין בינארי ב-PATH",
    pytesseract_import_failed:
      "לא ניתן לטעון pytesseract או לקרוא ל-Tesseract (בדוק התקנה)",
    hebrew_lang_pack_missing:
      "חסרה חבילת עברית (heb) ל-Tesseract — התקן tesseract-lang",
  };
  return (
    byReason[reason ?? ""] ??
    "לא ניתן להריץ OCR לשם הקניין (בדוק התקנת Tesseract; ב-Vercel לרוב נדרש Docker או worker)"
  );
}

const COLUMNS = [
  "מספר שורה",
  "מספר בלם",
  "שם קניין",
  "תאריך סופי להגשה",
  "מקט רפאל",
  "כמות נדרשת",
  "זמן אספקה בשבועות",
  "FAI",
];

export default function RafaelTab() {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<RafaelResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  function handleFile(f: File | null) {
    setFile(f);
    setData(null);
    setError(null);
    setSuccess(null);
  }

  async function handleExtract() {
    if (!file) return;
    setLoading(true);
    setError(null);
    setSuccess(null);
    setData(null);

    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch("/api/rafael-bom", { method: "POST", body: fd });
      const json = await res.json();
      if (!res.ok) {
        const detail =
          typeof json?.error === "string"
            ? json.error
            : typeof json?.detail === "string"
              ? json.detail
              : undefined;
        setError(appendDataCheckHint(detail, "rafael"));
        return;
      }
      setData(json as RafaelResponse);
      setSuccess(
        `הנתונים חולצו בהצלחה – נמצאו ${json.rows.length} שורות אספקה`,
      );
    } catch {
      setError(appendDataCheckHint("שגיאה בתקשורת עם השרת", "rafael"));
    } finally {
      setLoading(false);
    }
  }

  function handleDownloadTxt() {
    if (!data) return;
    downloadBase64(
      data.txt_base64,
      data.txt_filename,
      "text/plain;charset=windows-1255",
    );
  }

  function handleNewRun() {
    setFile(null);
    setData(null);
    setError(null);
    setSuccess(null);
  }

  const showNewRun = Boolean(data || error || success);

  const buyerDisplay = useMemo(() => {
    if (!data) return "—";
    return rafaelBuyerDisplayLabel(data.buyer_name, data.buyer_ocr_reason);
  }, [data]);

  const tableRows = useMemo(() => {
    if (!data) return [];
    const label = rafaelBuyerDisplayLabel(
      data.buyer_name,
      data.buyer_ocr_reason,
    );
    if (data.buyer_name !== "OCR Failed") return data.rows;
    return data.rows.map((row) =>
      row["שם קניין"] === "OCR Failed"
        ? { ...row, "שם קניין": label }
        : row,
    );
  }, [data]);

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-gray-700">
        העלה קובץ RFQ של רפאל וקבל בשניות את כל שורות האספקה (מק״ט, כמות,
        שבועות ARO, FAI) מוכנות לשימוש ב-Excel.
      </p>

      <FileDropzone
        label="גרור לכאן קובץ RFQ של רפאל (PDF) או לחץ לבחירה"
        file={file}
        onFile={handleFile}
        onError={(msg) => setError(msg)}
        disabled={loading}
        belowDropzone={
          showNewRun ? (
            <button
              type="button"
              onClick={handleNewRun}
              className="w-full rounded-lg border border-nativ-dark/20 bg-white px-4 py-2.5 font-semibold text-nativ-dark shadow-sm transition-colors hover:bg-gray-50"
            >
              להרצה חדשה
            </button>
          ) : null
        }
      />

      {file && (
        <button
          onClick={handleExtract}
          disabled={loading}
          className="w-full rounded-lg bg-nativ-gold px-4 py-2.5 font-semibold text-white shadow-sm transition-colors hover:bg-nativ-gold-hover disabled:cursor-not-allowed disabled:opacity-60"
        >
          {loading ? "מעבד קובץ..." : "חלץ נתונים"}
        </button>
      )}

      {loading && <ProcessingStatus variant="rafael" />}

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">
          {error}
        </div>
      )}

      {success && (
        <div className="rounded-lg border border-green-200 bg-green-50 px-4 py-2.5 text-sm text-green-700">
          {success}
        </div>
      )}

      {data && (
        <>
          <InfoCard
            items={[
              { label: "מספר בלם", value: data.rfq_number },
              { label: "שם קניין", value: buyerDisplay },
              { label: "תאריך סופי להגשה", value: data.submission_date || "—" },
            ]}
          />

          <div className="text-base font-bold text-nativ-dark mt-2">
            שורות אספקה
          </div>
          <button
            type="button"
            onClick={handleDownloadTxt}
            className="w-full rounded-lg bg-nativ-gold px-4 py-2.5 font-semibold text-white shadow-sm transition-colors hover:bg-nativ-gold-hover"
          >
            הורד קובץ TXT (מופרד בטאב · Excel)
          </button>
          <DataTable columns={COLUMNS} rows={tableRows} />
        </>
      )}
    </div>
  );
}
