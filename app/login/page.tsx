"use client";

import { useState, FormEvent } from "react";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      if (res.ok) {
        router.replace("/");
        router.refresh();
      } else {
        setError("סיסמה שגויה, נסה שנית.");
      }
    } catch {
      setError("שגיאה בתקשורת עם השרת.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col items-center min-h-screen bg-gray-50">
      <header className="w-full max-w-2xl mx-auto pt-10 pb-4 text-center">
        <h1 className="text-4xl font-extrabold text-primary tracking-tight">
          נתיב | Nativ
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          חילוץ נתונים חכם ממסמכי רכש ושרטוטים הנדסיים
        </p>
      </header>

      <hr className="w-full max-w-2xl border-t border-gray-200 mb-8" />

      <main className="w-full max-w-md mx-auto px-4">
        <form
          onSubmit={handleSubmit}
          className="bg-white border border-gray-200 rounded-xl p-6 shadow-sm"
        >
          <label
            htmlFor="password"
            className="block text-sm font-medium text-gray-700 mb-2"
          >
            סיסמה
          </label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoFocus
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-base focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          />

          {error && (
            <p className="mt-3 text-sm text-red-600 text-center">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading || password.length === 0}
            className="mt-4 w-full rounded-lg bg-primary px-4 py-2.5 text-white font-semibold hover:bg-primary-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? "..." : "כניסה"}
          </button>
        </form>
      </main>
    </div>
  );
}
