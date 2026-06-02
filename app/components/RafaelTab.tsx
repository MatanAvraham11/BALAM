"use client";

import { useMemo, useState } from "react";
import { useDropzone, type Accept } from "react-dropzone";
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
  rows: RafaelRow[];
  txt_base64: string;
  txt_filename: string;
};

type PlrRow = {
  operation_sequence: string;
  component_item: string;
  qty: string;
};

type ZipResponse = {
  rows: PlrRow[];
  matched_file_count: number;
  plreport_zip_count: number;
  xls_file_count: number;
  txt_base64: string;
  txt_filename: string;
};

const PLR_COLUMNS = ["Operation Sequence", "Component Item", "QTY"];

const RAFAEL_UPLOAD_ACCEPT: Accept = {
  "application/pdf": [".pdf"],
  "application/zip": [".zip"],
  "application/x-zip-compressed": [".zip"],
  "multipart/x-zip": [".zip"],
  "application/octet-stream": [".pdf", ".zip"],
};

function apiErrorMessages(json: unknown, fallback: string): string[] {
  if (json && typeof json === "object") {
    const record = json as Record<string, unknown>;
    const raw = record.error ?? record.detail;
    if (Array.isArray(raw)) {
      const messages = raw
        .map((item) => String(item).trim())
        .filter((item) => item.length > 0);
      if (messages.length > 0) return messages;
    }
    if (typeof raw === "string" && raw.trim()) {
      return [raw.trim()];
    }
  }
  return [fallback];
}

function ZipErrorList({ errors }: { errors: string[] }) {
  if (errors.length === 0) return null;
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">
      <div className="font-semibold">שגיאה בפענוח ה-ZIP:</div>
      {errors.length === 1 ? (
        <div className="mt-1">{errors[0]}</div>
      ) : (
        <ul className="mt-1 list-inside list-disc space-y-0.5">
          {errors.map((msg, i) => (
            <li key={i}>{msg}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

type RafaelFilesDropzoneProps = {
  pdfFile: File | null;
  zipFile: File | null;
  disabled?: boolean;
  showNewRun: boolean;
  onPdfFile: (file: File | null) => void;
  onZipFile: (file: File | null) => void;
  onError: (message: string) => void;
  onNewRun: () => void;
};

function fileKind(file: File | null | undefined): "pdf" | "zip" | null {
  const name = typeof file?.name === "string" ? file.name.toLowerCase() : "";
  if (name.endsWith(".pdf")) return "pdf";
  if (name.endsWith(".zip")) return "zip";
  return null;
}

function uploadBatchError(files: Array<File | null | undefined>): string | null {
  if (files.length > 2) {
    return "ניתן להעלות עד שני קבצים: PDF אחד ו-ZIP אחד.";
  }

  if (files.some((file) => !fileKind(file))) {
    return "סוג קובץ לא תקין. יש להעלות PDF ו/או ZIP בלבד.";
  }

  const pdfCount = files.filter((file) => fileKind(file) === "pdf").length;
  const zipCount = files.filter((file) => fileKind(file) === "zip").length;
  if (pdfCount > 1 || zipCount > 1) {
    return "יש להעלות לכל היותר קובץ PDF אחד וקובץ ZIP אחד.";
  }

  return null;
}

function RafaelFilesDropzone({
  pdfFile,
  zipFile,
  disabled,
  showNewRun,
  onPdfFile,
  onZipFile,
  onError,
  onNewRun,
}: RafaelFilesDropzoneProps) {
  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept: RAFAEL_UPLOAD_ACCEPT,
    multiple: true,
    maxFiles: 2,
    maxSize: 50 * 1024 * 1024,
    disabled,
    validator: (file) => {
      if (!fileKind(file)) {
        return {
          code: "file-invalid-type",
          message: "PDF or ZIP extension required",
        };
      }
      return null;
    },
    onDrop: (accepted, rejected) => {
      const droppedFiles = [
        ...accepted,
        ...rejected.map((rejection) => rejection.file),
      ];
      const batchError = uploadBatchError(droppedFiles);
      if (batchError) {
        onError(batchError);
        return;
      }

      const tooLarge = rejected.some((rejection) =>
        rejection.errors.some((error) => error.code === "file-too-large"),
      );
      if (tooLarge) {
        onError("הקובץ גדול מדי. יש להעלות כל קובץ עד 50MB.");
        return;
      }

      if (rejected.length > 0) {
        onError("סוג קובץ לא תקין. יש להעלות PDF ו/או ZIP בלבד.");
        return;
      }

      const pdfs = accepted.filter((candidate) => fileKind(candidate) === "pdf");
      const zips = accepted.filter((candidate) => fileKind(candidate) === "zip");
      if (pdfs[0]) onPdfFile(pdfs[0]);
      if (zips[0]) onZipFile(zips[0]);
    },
    onDropRejected: (rejections) => {
      const code = rejections[0]?.errors?.[0]?.code ?? "";
      if (code === "file-too-large") {
        onError("הקובץ גדול מדי. יש להעלות כל קובץ עד 50MB.");
      } else if (code === "too-many-files") {
        onError("ניתן להעלות עד שני קבצים: PDF אחד ו-ZIP אחד.");
      } else {
        onError("סוג קובץ לא תקין. יש להעלות PDF ו/או ZIP בלבד.");
      }
    },
  });

  return (
    <div className="space-y-3">
      <div
        {...getRootProps()}
        className={`w-full cursor-pointer rounded-xl border-2 border-dashed bg-white px-5 py-8 text-center shadow-sm transition-colors ${
          isDragActive
            ? "border-nativ-gold bg-nativ-gold/5"
            : "border-gray-200 hover:border-nativ-gold/50 hover:bg-nativ-gold/5"
        } ${disabled ? "cursor-not-allowed opacity-60" : ""}`}
      >
        <input {...getInputProps()} />
        <p className="text-sm font-semibold text-gray-900">
          גרור לכאן PDF של RFQ ו-ZIP של נתוני ייצור או לחץ לבחירה
        </p>
        <div className="mt-3 space-y-1 text-xs text-gray-600">
          {pdfFile || zipFile ? (
            <>
              {pdfFile ? (
                <p>
                  PDF: <span className="font-semibold text-nativ-gold">{pdfFile.name}</span>
                </p>
              ) : (
                <p className="text-gray-400">PDF חסר</p>
              )}
              {zipFile ? (
                <p>
                  ZIP: <span className="font-semibold text-nativ-gold">{zipFile.name}</span>
                </p>
              ) : (
                <p className="text-gray-400">ZIP חסר</p>
              )}
            </>
          ) : (
            <p>PDF ו-ZIP בלבד · אפשר להעלות ביחד או אחד-אחד</p>
          )}
        </div>
      </div>

      {showNewRun ? (
        <button
          type="button"
          onClick={onNewRun}
          className="w-full rounded-lg border border-nativ-dark/20 bg-white px-4 py-2.5 font-semibold text-nativ-dark shadow-sm transition-colors hover:bg-gray-50"
        >
          להרצה חדשה
        </button>
      ) : null}

      <div className="flex items-start gap-2 rounded-lg border border-nativ-gold/20 bg-nativ-gold/5 px-4 py-3 text-sm text-nativ-dark/80">
        <svg
          aria-hidden="true"
          viewBox="0 0 24 24"
          className="mt-0.5 h-5 w-5 shrink-0 text-nativ-gold"
          fill="none"
          stroke="currentColor"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="2"
        >
          <rect x="5" y="11" width="14" height="10" rx="2" />
          <path d="M8 11V7a4 4 0 0 1 8 0v4" />
        </svg>
        <p>
          אבטחת מידע תעשייתית: ניתוח הקבצים מתבצע בשרת מקומי. הקבצים אינם
          נשמרים, ואינם משותפים עם שום צד שלישי
        </p>
      </div>
    </div>
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

  // ZIP state
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [zipLoading, setZipLoading] = useState(false);
  const [zipData, setZipData] = useState<ZipResponse | null>(null);
  const [zipErrors, setZipErrors] = useState<string[]>([]);

  /** First rafael part number from the PDF result — used as the sort key for PLR files. */
  const parentPn = useMemo(() => {
    const first = data?.rows?.[0]?.["מקט רפאל"];
    return (first || "").trim();
  }, [data]);

  function handleFile(f: File | null) {
    setFile(f);
    setData(null);
    setError(null);
    setSuccess(null);
    setZipData(null);
    setZipErrors([]);
  }

  function handleZipFile(f: File | null) {
    setZipFile(f);
    setError(null);
    setZipData(null);
    setZipErrors([]);
  }

  async function handleExtract() {
    if (!file) return;
    setLoading(true);
    setError(null);
    setSuccess(null);
    setData(null);
    setZipData(null);
    setZipErrors([]);

    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch("/api/rafael-bom", { method: "POST", body: fd });
      const json = await res.json();
      if (!res.ok) {
        const detail = apiErrorMessages(json, "שגיאה בפענוח ה-PDF")[0];
        setError(appendDataCheckHint(detail, "rafael"));
        return;
      }
      const pdfData = json as RafaelResponse;
      setData(pdfData);
      setSuccess(
        `הנתונים חולצו בהצלחה – נמצאו ${json.rows.length} שורות אספקה`,
      );
      if (zipFile) {
        const zipParentPn = (pdfData.rows?.[0]?.["מקט רפאל"] || "").trim();
        await extractZip(zipFile, zipParentPn);
      }
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

  function handleDownloadPlrTxt() {
    if (!zipData) return;
    downloadBase64(
      zipData.txt_base64,
      zipData.txt_filename,
      "text/plain;charset=windows-1255",
    );
  }

  async function extractZip(selectedZipFile: File, selectedParentPn: string) {
    setZipLoading(true);
    setZipErrors([]);
    setZipData(null);

    try {
      const fd = new FormData();
      fd.append("file", selectedZipFile);
      fd.append("parent_part_number", selectedParentPn);
      const res = await fetch("/api/rafael-zip", { method: "POST", body: fd });
      const json = await res.json();
      if (!res.ok) {
        setZipErrors(apiErrorMessages(json, "שגיאה בפענוח ה-ZIP"));
        return;
      }
      setZipData(json as ZipResponse);
    } catch {
      setZipErrors(["שגיאה בתקשורת עם השרת בעת עיבוד ה-ZIP"]);
    } finally {
      setZipLoading(false);
    }
  }

  async function handleZipExtract() {
    if (!zipFile) return;
    await extractZip(zipFile, parentPn);
  }

  function handleNewRun() {
    setFile(null);
    setData(null);
    setError(null);
    setSuccess(null);
    setZipFile(null);
    setZipData(null);
    setZipErrors([]);
  }

  const showNewRun = Boolean(
    data || error || success || zipData || zipErrors.length,
  );

  const buyerDisplay = useMemo(() => {
    if (!data) return "—";
    return data.buyer_name.trim() || "—";
  }, [data]);

  const tableRows = useMemo(() => {
    if (!data) return [];
    return data.rows;
  }, [data]);

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-gray-700">
        העלה קובץ RFQ של רפאל וקובץ ZIP של נתוני ייצור כדי לקבל את שורות
        האספקה ואת טבלת ה-PLR מוכנות לשימוש ב-Excel.
      </p>

      <RafaelFilesDropzone
        pdfFile={file}
        zipFile={zipFile}
        disabled={loading || zipLoading}
        showNewRun={showNewRun}
        onPdfFile={handleFile}
        onZipFile={handleZipFile}
        onError={(msg) => setError(msg)}
        onNewRun={handleNewRun}
      />

      {file && (
        <button
          type="button"
          onClick={handleExtract}
          disabled={loading || zipLoading}
          className="w-full rounded-lg bg-nativ-gold px-4 py-2.5 font-semibold text-white shadow-sm transition-colors hover:bg-nativ-gold-hover disabled:cursor-not-allowed disabled:opacity-60"
        >
          {loading || zipLoading
            ? zipLoading
              ? "מעבד ZIP..."
              : "מעבד קובץ..."
            : zipFile
              ? "חלץ PDF ו-ZIP"
              : "חלץ נתוני PDF"}
        </button>
      )}

      {loading && <ProcessingStatus variant="rafael" />}

      {!data && <ZipErrorList errors={zipErrors} />}

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

          {(zipFile || zipLoading || zipData || zipErrors.length > 0) && (
          <div className="mt-6 flex flex-col gap-4 border-t border-gray-200 pt-4">
            <div className="text-base font-bold text-nativ-dark">
              נתוני ייצור PLR
            </div>

            {zipFile && !zipData && !zipLoading && zipErrors.length === 0 && (
              <button
                type="button"
                onClick={handleZipExtract}
                disabled={zipLoading}
                className="w-full rounded-lg bg-nativ-gold px-4 py-2.5 font-semibold text-white shadow-sm transition-colors hover:bg-nativ-gold-hover disabled:cursor-not-allowed disabled:opacity-60"
              >
                {zipLoading ? "מעבד ZIP..." : "חלץ נתוני ייצור"}
              </button>
            )}

            {zipLoading && (
              <div className="text-sm text-gray-500 animate-pulse">מעבד קובץ ZIP...</div>
            )}

            <ZipErrorList errors={zipErrors} />

            {zipData && (
              <>
                <div className="flex items-center gap-3 text-sm text-gray-600">
                  <span>
                    נמצאו{" "}
                    <span className="font-semibold text-nativ-dark">
                      {zipData.rows.length}
                    </span>{" "}
                    שורות מתוך{" "}
                    <span className="font-semibold">
                      {zipData.xls_file_count}
                    </span>{" "}
                    קבצי XLS
                    {zipData.matched_file_count > 0 && (
                      <span className="text-green-700">
                        {" "}({zipData.matched_file_count} תואמים למק״ט הורה)
                      </span>
                    )}
                  </span>
                </div>

                <button
                  type="button"
                  onClick={handleDownloadPlrTxt}
                  className="w-full rounded-lg bg-nativ-gold px-4 py-2.5 font-semibold text-white shadow-sm transition-colors hover:bg-nativ-gold-hover"
                >
                  הורד קובץ PLR TXT (מופרד בטאב · Excel)
                </button>

                <DataTable
                  columns={PLR_COLUMNS}
                  rows={zipData.rows.map((r) => ({
                    "Operation Sequence": r.operation_sequence,
                    "Component Item": r.component_item,
                    "QTY": r.qty,
                  }))}
                />
              </>
            )}
          </div>
          )}
        </>
      )}
    </div>
  );
}
