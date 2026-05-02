"use client";

import { useState } from "react";

const ISSUE_TYPES = [
  { value: "", label: "בחרו סוג פנייה" },
  { value: "תקלה טכנית", label: "תקלה טכנית" },
  { value: "שאלה כללית", label: "שאלה כללית" },
  { value: "בקשת סיוע בתהליך", label: "בקשת סיוע בתהליך" },
  { value: "אחר", label: "אחר" },
];

export default function SupportForm() {
  const [fullName, setFullName] = useState("");
  const [company, setCompany] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [issueType, setIssueType] = useState("");
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
          formType: "Support",
          fullName,
          company,
          phone,
          email,
          issueType,
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
      setPhone("");
      setEmail("");
      setIssueType("");
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
    <form onSubmit={onSubmit} className="space-y-5 rounded-xl border border-stone-200 bg-white p-6 shadow-sm sm:p-8">
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
        <label htmlFor="sf-name" className="text-sm font-medium text-nativ-dark">
          שם מלא <span className="text-red-600">*</span>
        </label>
        <input
          id="sf-name"
          name="fullName"
          required
          autoComplete="name"
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          className={inputClass}
        />
      </div>
      <div>
        <label htmlFor="sf-company" className="text-sm font-medium text-nativ-dark">
          שם חברה <span className="text-red-600">*</span>
        </label>
        <input
          id="sf-company"
          name="company"
          required
          autoComplete="organization"
          value={company}
          onChange={(e) => setCompany(e.target.value)}
          className={inputClass}
        />
      </div>
      <div>
        <label htmlFor="sf-phone" className="text-sm font-medium text-nativ-dark">
          טלפון <span className="text-red-600">*</span>
        </label>
        <input
          id="sf-phone"
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
        <label htmlFor="sf-email" className="text-sm font-medium text-nativ-dark">
          אימייל <span className="text-red-600">*</span>
        </label>
        <input
          id="sf-email"
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
        <label htmlFor="sf-issue" className="text-sm font-medium text-nativ-dark">
          סוג פנייה <span className="text-red-600">*</span>
        </label>
        <select
          id="sf-issue"
          name="issueType"
          required
          value={issueType}
          onChange={(e) => setIssueType(e.target.value)}
          className={inputClass}
        >
          {ISSUE_TYPES.map((o) => (
            <option key={o.value || "empty"} value={o.value} disabled={o.value === ""}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label htmlFor="sf-desc" className="text-sm font-medium text-nativ-dark">
          תיאור הפנייה <span className="text-red-600">*</span>
        </label>
        <textarea
          id="sf-desc"
          name="description"
          required
          rows={5}
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
        {loading ? "שולח…" : "שליחת פנייה לתמיכה"}
      </button>
    </form>
  );
}
