"use client";

import { useMemo, useState } from "react";
import FileDropzone from "./FileDropzone";
import DataTable from "./DataTable";
import ProcessingStatus from "./ProcessingStatus";
import { downloadBase64 } from "../lib/download";

type FAIItem = {
  balloon_number: number;
  text: string;
  dimension_type: string;
  tolerance: string;
};

type DrawingResponse = {
  items: FAIItem[];
  csv_base64: string;
  csv_filename: string;
  annotated_pdf_base64: string;
  annotated_pdf_filename: string;
};

const COLUMNS = ["מספר בלון", "מידה / הערה", "סוג מידה", "טולרנס", "נמצא"];

export default function DrawingTab() {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<DrawingResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const rows = useMemo(
    () =>
      (data?.items ?? []).map((it) => ({
        "מספר בלון": it.balloon_number,
        "מידה / הערה": it.text,
        "סוג מידה": it.dimension_type,
        "טולרנס": it.tolerance,
        "נמצא": "",
      })),
    [data],
  );

  const pdfDataUrl = useMemo(
    () =>
      data
        ? `data:application/pdf;base64,${data.annotated_pdf_base64}`
        : null,
    [data],
  );

  async function handleExtract() {
    if (!file) return;
    setLoading(true);
    setError(null);
    setSuccess(null);
    setData(null);

    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch("/api/drawing", { method: "POST", body: fd });
      const json = await res.json();
      if (!res.ok) {
        setError(json?.error || json?.detail || "שגיאה בניתוח השרטוט");
        return;
      }
      setData(json as DrawingResponse);
      setSuccess(`זוהו ${json.items.length} מידות/הערות בשרטוט`);
    } catch {
      setError("שגיאה בתקשורת עם השרת");
    } finally {
      setLoading(false);
    }
  }

  function handleDownloadCsv() {
    if (!data) return;
    downloadBase64(data.csv_base64, data.csv_filename, "text/csv");
  }

  function handleDownloadPdf() {
    if (!data) return;
    downloadBase64(
      data.annotated_pdf_base64,
      data.annotated_pdf_filename,
      "application/pdf",
    );
  }

  function handleNewRun() {
    setFile(null);
    setData(null);
    setError(null);
    setSuccess(null);
  }

  const showNewRun = Boolean(file || data || error || success);

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-gray-700">
        העלה שרטוט הנדסי (PDF) — נחלץ את כל המידות, נמספר אותן ונחזיר CSV וגם
        שרטוט ממוספר.
      </p>

      <FileDropzone
        label="גרור לכאן שרטוט הנדסי (PDF) או לחץ לבחירה"
        file={file}
        onFile={setFile}
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
          {loading ? "מעבד קובץ..." : "חלץ מידות"}
        </button>
      )}

      {loading && <ProcessingStatus />}

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">
          שגיאה בניתוח השרטוט: {error}
        </div>
      )}

      {success && (
        <div className="rounded-lg border border-green-200 bg-green-50 px-4 py-2.5 text-sm text-green-700">
          {success}
        </div>
      )}

      {data && (
        <>
          <div className="text-base font-bold text-nativ-dark mt-2">
            טבלת מידות
          </div>
          <button
            onClick={handleDownloadCsv}
            className="w-full rounded-lg bg-nativ-gold px-4 py-2.5 font-semibold text-white shadow-sm transition-colors hover:bg-nativ-gold-hover"
          >
            הורד כ-Excel / CSV
          </button>
          <DataTable columns={COLUMNS} rows={rows} />

          <div className="text-base font-bold text-nativ-dark mt-2">
            שרטוט ממוספר
          </div>
          {pdfDataUrl && (
            <iframe
              src={pdfDataUrl}
              title="annotated drawing"
              className="w-full h-[600px] rounded-xl border border-gray-200 bg-white"
            />
          )}

          <button
            onClick={handleDownloadPdf}
            className="w-full rounded-lg border border-nativ-gold/30 bg-white px-4 py-2.5 font-semibold text-nativ-gold shadow-sm transition-colors hover:bg-nativ-gold/5"
          >
            הורד שרטוט ממוספר (PDF)
          </button>
        </>
      )}
    </div>
  );
}
