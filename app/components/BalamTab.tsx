"use client";

import { useState } from "react";
import FileDropzone from "./FileDropzone";
import InfoCard from "./InfoCard";
import DataTable from "./DataTable";
import ProcessingStatus from "./ProcessingStatus";
import { downloadBase64 } from "../lib/download";

type BalamRow = {
  "מספר": number;
  'מק"ט ספק': string;
  "כמות נדרשת": number;
  "הוצאה": string;
};

type BalamResponse = {
  balam_number: string;
  buyer_name: string;
  aggregated_rows: BalamRow[];
  csv_base64: string;
  csv_filename: string;
};

const COLUMNS = ["מספר", 'מק"ט ספק', "כמות נדרשת", "הוצאה"];

export default function BalamTab() {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<BalamResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  async function handleExtract() {
    if (!file) return;
    setLoading(true);
    setError(null);
    setSuccess(null);
    setData(null);

    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch("/api/balam", { method: "POST", body: fd });
      const json = await res.json();
      if (!res.ok) {
        setError(json?.error || json?.detail || "שגיאה בעיבוד הקובץ");
        return;
      }
      setData(json as BalamResponse);
      setSuccess(
        `הנתונים חולצו בהצלחה – נמצאו ${json.aggregated_rows.length} פריטים`,
      );
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

  function handleNewRun() {
    setFile(null);
    setData(null);
    setError(null);
    setSuccess(null);
  }

  const showNewRun = Boolean(data || error || success);

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-gray-700">
        העלה קובץ PDF של בל״מ וקבל בשניות את כל הנתונים הרלוונטיים מוכנים
        לשימוש.
      </p>

      <FileDropzone
        label='גרור לכאן קובץ בל"מ (PDF) או לחץ לבחירה'
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
          {loading ? "מעבד קובץ..." : "חלץ נתונים"}
        </button>
      )}

      {loading && <ProcessingStatus />}

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">
          שגיאה בעיבוד הקובץ: {error}
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
              { label: 'מספר בל"מ', value: data.balam_number },
              { label: "קניין", value: data.buyer_name },
            ]}
          />

          <div className="text-base font-bold text-nativ-dark mt-2">
            נתוני הפריטים
          </div>
          <button
            onClick={handleDownloadCsv}
            className="w-full rounded-lg bg-nativ-gold px-4 py-2.5 font-semibold text-white shadow-sm transition-colors hover:bg-nativ-gold-hover"
          >
            הורד כ-Excel / CSV
          </button>
          <DataTable columns={COLUMNS} rows={data.aggregated_rows} />
        </>
      )}
    </div>
  );
}
