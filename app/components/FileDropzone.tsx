"use client";

import { useDropzone } from "react-dropzone";

type Props = {
  label: string;
  file: File | null;
  onFile: (f: File | null) => void;
  disabled?: boolean;
};

export default function FileDropzone({ label, file, onFile, disabled }: Props) {
  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept: { "application/pdf": [".pdf"] },
    multiple: false,
    disabled,
    onDrop: (accepted) => {
      if (accepted.length > 0) onFile(accepted[0]);
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
          <p className="mt-2 text-xs text-gray-500">PDF בלבד</p>
        )}
      </div>

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
