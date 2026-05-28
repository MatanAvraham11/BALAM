"use client";

import type { ReactNode } from "react";
import { useDropzone, type Accept } from "react-dropzone";

export const ACCEPT_PDF: Accept = { "application/pdf": [".pdf"] };

export const ACCEPT_ZIP: Accept = {
  "application/zip": [".zip"],
  "application/x-zip-compressed": [".zip"],
  "multipart/x-zip": [".zip"],
  /** macOS / some browsers label ZIP as octet-stream — restrict to .zip extension */
  "application/octet-stream": [".zip"],
};

export type FileDropzoneAcceptKind = "pdf" | "zip";

const ACCEPT_BY_KIND: Record<FileDropzoneAcceptKind, Accept> = {
  pdf: ACCEPT_PDF,
  zip: ACCEPT_ZIP,
};

const HINT_BY_KIND: Record<FileDropzoneAcceptKind, string> = {
  pdf: "PDF בלבד",
  zip: "ZIP בלבד",
};

type Props = {
  label: string;
  file: File | null;
  onFile: (f: File | null) => void;
  disabled?: boolean;
  /** Which file types to accept. Defaults to PDF (existing tabs). */
  acceptKind?: FileDropzoneAcceptKind;
  /** Rendered directly under the dashed drop zone, above the security notice */
  belowDropzone?: ReactNode;
  /** Called with a human-readable message when a file is rejected */
  onError?: (msg: string) => void;
};

export default function FileDropzone({
  label,
  file,
  onFile,
  disabled,
  acceptKind = "pdf",
  belowDropzone,
  onError,
}: Props) {
  const kindLabel = acceptKind === "zip" ? "ZIP" : "PDF";

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept: ACCEPT_BY_KIND[acceptKind],
    multiple: false,
    maxSize: 50 * 1024 * 1024,
    disabled,
    validator: (file) => {
      if (acceptKind === "zip" && !file.name.toLowerCase().endsWith(".zip")) {
        return {
          code: "file-invalid-type",
          message: "ZIP extension required",
        };
      }
      return null;
    },
    onDrop: (accepted) => {
      if (accepted.length > 0) onFile(accepted[0]);
    },
    onDropRejected: (rejections) => {
      if (!onError) return;
      const first = rejections[0];
      const code = first?.errors?.[0]?.code ?? "";
      if (code === "file-invalid-type") {
        onError(`סוג קובץ לא תקין. יש להעלות קובץ ${kindLabel} בלבד.`);
      } else if (code === "file-too-large") {
        onError("הקובץ גדול מדי. יש להעלות קובץ עד 50MB.");
      } else if (code === "too-many-files") {
        onError("ניתן להעלות קובץ אחד בלבד.");
      } else {
        onError(`הקובץ נדחה. יש להעלות קובץ ${kindLabel} תקין.`);
      }
    },
  });

  return (
    <div className="space-y-3">
      <div
        {...getRootProps()}
        className={`w-full rounded-xl border-2 border-dashed px-5 py-8 cursor-pointer bg-white text-center shadow-sm transition-colors ${
          isDragActive
            ? "border-nativ-gold bg-nativ-gold/5"
            : "border-gray-200 hover:border-nativ-gold/50 hover:bg-nativ-gold/5"
        } ${disabled ? "opacity-60 cursor-not-allowed" : ""}`}
      >
        <input {...getInputProps()} />
        <p className="text-sm font-semibold text-gray-900">{label}</p>
        {file ? (
          <p className="mt-2 text-xs text-nativ-gold">
            נבחר: <span className="font-semibold">{file.name}</span>
          </p>
        ) : (
          <p className="mt-2 text-xs text-gray-500">{HINT_BY_KIND[acceptKind]}</p>
        )}
      </div>

      {belowDropzone}

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
          אבטחת מידע תעשייתית: ניתוח השרטוט מתבצע בשרת מקומי. הקבצים אינם
          נשמרים, ואינם משותפים עם שום צד שלישי
        </p>
      </div>
    </div>
  );
}
