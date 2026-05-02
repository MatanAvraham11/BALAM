"use client";

import { useState, FormEvent } from "react";
import SiteNav from "../components/SiteNav";

export default function LoginPage() {
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
        credentials: "same-origin",
        body: JSON.stringify({ password }),
      });
      if (res.ok) {
        window.location.assign("/");
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
    <div className="flex min-h-screen flex-col bg-nativ-light text-nativ-dark">
      <SiteNav />
      <div className="flex flex-1 flex-col items-center">
        <header className="w-full max-w-md px-4 pt-8 pb-2 text-center sm:px-6">
          <p className="text-xs leading-snug text-nativ-dark/70 sm:text-sm">
            מערכות ואוטומציות למפעלים
          </p>
          <p className="mt-2 text-sm font-medium text-nativ-dark">כניסה למערכת</p>
        </header>

        <hr className="mb-6 w-full max-w-md border-t border-gray-200 px-4 sm:px-6" />

        <main className="mx-auto w-full max-w-md flex-1 px-4 pb-12 sm:px-6">
        <form
          onSubmit={handleSubmit}
          className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm"
        >
          <label
            htmlFor="password"
            className="mb-2 block text-sm font-medium text-nativ-dark"
          >
            סיסמה
          </label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoFocus
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-base text-nativ-dark focus:border-nativ-gold focus:outline-none focus:ring-1 focus:ring-nativ-gold"
          />

          {error && (
            <p className="mt-3 text-center text-sm text-red-600">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading || password.length === 0}
            className="mt-4 w-full rounded-lg bg-nativ-gold px-4 py-2.5 font-semibold text-white transition-colors hover:bg-nativ-gold-hover disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? "..." : "כניסה"}
          </button>
        </form>
        </main>
      </div>
    </div>
  );
}
