"use client";

import { useState } from "react";

export default function ContactForm() {
  const [fullName, setFullName] = useState("");
  const [company, setCompany] = useState("");
  const [role, setRole] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [description, setDescription] = useState("");
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setSuccess(false);
    try {
      const res = await fetch("/api/send-email", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          formType: "Contact",
          fullName,
          company,
          role: role || undefined,
          phone,
          email,
          description,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(typeof data.error === "string" ? data.error : "שגיאה בשליחה.");
        return;
      }
      setSuccess(true);
      setFullName("");
      setCompany("");
      setRole("");
      setPhone("");
      setEmail("");
      setDescription("");
    } catch {
      setError("שגיאת רשת. נסו שוב.");
    } finally {
      setLoading(false);
    }
  }

  const inputClass =
    "mt-1 w-full rounded-md border border-stone-300 bg-white px-3 py-2 text-sm text-nativ-dark shadow-sm outline-none transition-shadow focus:border-nativ-gold focus:ring-2 focus:ring-nativ-gold/25";

  return (
    <form
      id="quote"
      onSubmit={onSubmit}
      className="space-y-5 rounded-xl border border-stone-200 bg-white p-6 shadow-sm sm:p-8"
    >
      {success && (
        <p className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-900" role="status">
          הפנייה נשלחה בהצלחה. נחזור אליכם בהקדם.
        </p>
      )}
      {error && (
        <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-900" role="alert">
          {error}
        </p>
      )}

      <div>
        <label htmlFor="cf-name" className="text-sm font-medium text-nativ-dark">
          שם מלא <span className="text-red-600">*</span>
        </label>
        <input
          id="cf-name"
          name="fullName"
          required
          autoComplete="name"
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          className={inputClass}
        />
      </div>
      <div>
        <label htmlFor="cf-company" className="text-sm font-medium text-nativ-dark">
          שם חברה <span className="text-red-600">*</span>
        </label>
        <input
          id="cf-company"
          name="company"
          required
          autoComplete="organization"
          value={company}
          onChange={(e) => setCompany(e.target.value)}
          className={inputClass}
        />
      </div>
      <div>
        <label htmlFor="cf-role" className="text-sm font-medium text-nativ-dark">
          תפקיד
        </label>
        <input
          id="cf-role"
          name="role"
          autoComplete="organization-title"
          value={role}
          onChange={(e) => setRole(e.target.value)}
          className={inputClass}
        />
      </div>
      <div>
        <label htmlFor="cf-phone" className="text-sm font-medium text-nativ-dark">
          טלפון <span className="text-red-600">*</span>
        </label>
        <input
          id="cf-phone"
          name="phone"
          required
          type="tel"
          autoComplete="tel"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          className={inputClass}
        />
      </div>
      <div>
        <label htmlFor="cf-email" className="text-sm font-medium text-nativ-dark">
          אימייל <span className="text-red-600">*</span>
        </label>
        <input
          id="cf-email"
          name="email"
          required
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className={inputClass}
        />
      </div>
      <div>
        <label htmlFor="cf-desc" className="text-sm font-medium text-nativ-dark">
          תיאור קצר של הצורך <span className="text-red-600">*</span>
        </label>
        <textarea
          id="cf-desc"
          name="description"
          required
          rows={4}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          className={inputClass}
        />
      </div>

      <button
        type="submit"
        disabled={loading}
        className="w-full rounded-md bg-nativ-gold py-3 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-nativ-gold-hover disabled:cursor-not-allowed disabled:opacity-60 sm:w-auto sm:px-8"
      >
        {loading ? "שולח…" : "שליחת פנייה"}
      </button>
    </form>
  );
}
