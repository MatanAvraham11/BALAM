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
  /** Same as submission_date (V.6.0 alias). */
  submission_due_date?: string;
  buyer_ocr_ready?: boolean;
  buyer_ocr_reason?: string | null;
  buyer_ocr_http_status?: number | null;
  rows: RafaelRow[];
  txt_base64: string;
  txt_filename: string;
};

/** Human-readable Hebrew for buyer field: success, infra failure, or weak OCR. */
function rafaelBuyerDisplayLabel(
  buyerName: string,
  reason: string | null | undefined,
  httpStatus?: number | null,
): string {
  const t = (buyerName || "").trim();

  if (t && t !== "OCR Failed") {
    return t;
  }

  if (t === "OCR Failed") {
    const byReason: Record<string, string> = {
      rafael_buyer_ocr_disabled:
        "OCR לשם הקניין כבוי (הסר את RAFAEL_BUYER_OCR או הגדר לערך חיובי)",
      ocr_space_api_key_missing:
        "חסר מפתח OCR.space — הגדר OCR_SPACE_API_KEY בשרת (Vercel / worker)",
      requests_import_failed:
        "חסרה חבילת requests ב-Python (התקן requirements.txt)",
      tesseract_not_on_path:
        "חסר Tesseract בשרת (הודעה ישנה — V.5.9 משתמש ב-OCR.space)",
      pytesseract_import_failed:
        "שגיאת Tesseract/pytesseract (הודעה ישנה — V.5.9 משתמש ב-OCR.space)",
      hebrew_lang_pack_missing:
        "חבילת heb ל-Tesseract (הודעה ישנה — V.5.9 משתמש ב-OCR.space)",
    };
    return (
      byReason[reason ?? ""] ??
      "לא ניתן להריץ OCR לשם הקניין (בדוק OCR_SPACE_API_KEY ופריסת השרת)"
    );
  }

  const weakOcr: Record<string, string> = {
    ocr_space_no_hebrew:
      "OCR רץ אך לא זוהו מספיק אותיות עבריות בשם הקניין (נסה תמונה/מנוע אחר או RAFAEL_OCR_DEBUG=1)",
    ocr_space_parse_empty:
      "OCR.space לא החזיר טקסט מהאזור שנחתך — בדוק את ה-PDF או את מפתח ה-API",
    ocr_space_network_error:
      "אין תקשורת יציבה ל-OCR.space (פסק זמן או רשת). ניסינו שלוש פעמים — נסה שוב בעוד רגע",
    ocr_space_auth_error:
      "מפתח OCR.space נדחה (401/403) — בדוק שהמפתח נכון ובתוקף בחשבון OCR.space",
    ocr_space_rate_limited:
      "הגעת למכסת בקשות ל-OCR.space (429). המערכת כבר ניסתה שוב אוטומטית — המתן דקה ונסה שוב",
    ocr_space_payload_too_large:
      "התמונה ל-OCR.space גדולה מדי (413) — נסה RFQ אחר או פנה לתמיכה",
    ocr_space_quota_exceeded:
      "נראה שנגמרו קרדיטים או מכסה ב-OCR.space — היכנס לחשבון ובדוק את התוכנית",
    ocr_space_bad_request:
      "בקשה לא תקינה ל-OCR.space (400) — נסה שוב; אם חוזר, שלח לתמיכה את קוד ה-HTTP מהשרת",
    ocr_space_server_error:
      "שרת OCR.space החזיר שגיאה (5xx) אחרי ניסיונות חוזרים — נסה שוב בעוד דקות",
    ocr_space_client_error:
      "תשובת לקוח לא צפויה מ-OCR.space (קוד 4xx) — בדוק מפתח, חשבון, או חסימת רשת",
    ocr_space_http_error:
      "תשובת HTTP לא צפויה מ-OCR.space — נסה שוב; אם חוזר, RAFAEL_OCR_DEBUG=1 בשרת לפרטים",
    ocr_space_json_error:
      "תשובה לא תקינה מ-OCR.space (לא JSON) — בדוק רשת או פרוקסי",
  };
  if (!t && reason && weakOcr[reason]) {
    let msg = weakOcr[reason];
    if (
      typeof httpStatus === "number" &&
      httpStatus > 0 &&
      reason !== "ocr_space_network_error"
    ) {
      msg = `${msg} (קוד HTTP ${httpStatus})`;
    }
    return msg;
  }

  return t || "—";
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
    return rafaelBuyerDisplayLabel(
      data.buyer_name,
      data.buyer_ocr_reason,
      data.buyer_ocr_http_status,
    );
  }, [data]);

  const tableRows = useMemo(() => {
    if (!data) return [];
    const label = rafaelBuyerDisplayLabel(
      data.buyer_name,
      data.buyer_ocr_reason,
      data.buyer_ocr_http_status,
    );
    const replaceBuyerCell =
      data.buyer_name === "OCR Failed" ||
      (!(data.buyer_name || "").trim() && Boolean(data.buyer_ocr_reason));
    if (!replaceBuyerCell) return data.rows;
    return data.rows.map((row) => ({
      ...row,
      "שם קניין": label,
    }));
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
