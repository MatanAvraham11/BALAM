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
    <div
      {...getRootProps()}
      className={`w-full rounded-xl border-2 border-dashed px-4 py-6 cursor-pointer transition-colors text-center ${
        isDragActive
          ? "border-primary bg-blue-50"
          : "border-gray-300 bg-white hover:border-gray-400"
      } ${disabled ? "opacity-60 cursor-not-allowed" : ""}`}
    >
      <input {...getInputProps()} />
      <p className="text-sm text-gray-700 font-medium">{label}</p>
      {file ? (
        <p className="mt-2 text-xs text-gray-600">
          נבחר: <span className="font-semibold">{file.name}</span>
        </p>
      ) : (
        <p className="mt-2 text-xs text-gray-400">PDF בלבד</p>
      )}
    </div>
  );
}
