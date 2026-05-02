import { NextResponse } from "next/server";
import { Resend } from "resend";

export const runtime = "nodejs";

/** Resend sandbox default sender — single line; env may accidentally contain newlines. */
const DEFAULT_RESEND_FROM = "onboarding@resend.dev";

type FormType = "Contact" | "Support";

/** Strip whitespace/newlines so pasted env values like "onboarding@\nresend.dev" work. */
function normalizeEmailLike(value: string): string {
  return value.replace(/\s/g, "").trim();
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function buildHtmlBody(fields: Record<string, string | undefined>): string {
  const rows = Object.entries(fields)
    .filter(([, v]) => v !== undefined && String(v).trim() !== "")
    .map(
      ([k, v]) =>
        `<tr><td style="padding:8px 12px;border:1px solid #e5e5e5;background:#fafafa;font-weight:600;">${escapeHtml(k)}</td><td style="padding:8px 12px;border:1px solid #e5e5e5;">${escapeHtml(String(v))}</td></tr>`,
    )
    .join("");
  return `<!DOCTYPE html><html lang="he" dir="rtl"><head><meta charset="utf-8"/></head><body style="font-family:Arial,sans-serif;background:#f2f0ef;color:#323233;padding:24px;text-align:right;direction:rtl;"><table style="border-collapse:collapse;width:100%;max-width:560px;margin:0 auto;background:#fff;border-radius:8px;overflow:hidden;">${rows}</table></body></html>`;
}

export async function POST(request: Request) {
  const apiKey = process.env.RESEND_API_KEY;
  if (!apiKey) {
    return NextResponse.json(
      { error: "שירות המייל אינו מוגדר כרגע." },
      { status: 503 },
    );
  }

  let body: Record<string, unknown>;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "גוף הבקשה אינו JSON תקין." }, { status: 400 });
  }

  const formType = body.formType as FormType | undefined;
  const fullName = typeof body.fullName === "string" ? body.fullName.trim() : "";
  const company = typeof body.company === "string" ? body.company.trim() : "";
  const role = typeof body.role === "string" ? body.role.trim() : "";
  const phone = typeof body.phone === "string" ? body.phone.trim() : "";
  const email = typeof body.email === "string" ? body.email.trim() : "";
  const description =
    typeof body.description === "string" ? body.description.trim() : "";
  const issueType =
    typeof body.issueType === "string" ? body.issueType.trim() : "";

  if (formType !== "Contact" && formType !== "Support") {
    return NextResponse.json({ error: "סוג טופס לא תקין." }, { status: 400 });
  }

  if (!fullName || !company || !phone || !email || !description) {
    return NextResponse.json(
      { error: "יש למלא את כל השדות הנדרשים." },
      { status: 400 },
    );
  }

  if (formType === "Support" && !issueType) {
    return NextResponse.json(
      { error: "יש לבחור סוג פנייה." },
      { status: 400 },
    );
  }

  const emailRe = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  if (!emailRe.test(email)) {
    return NextResponse.json({ error: "כתובת האימייל אינה תקינה." }, { status: 400 });
  }

  const to = normalizeEmailLike(
    process.env.CONTACT_EMAIL_TO || process.env.ADMIN_EMAIL || "",
  );

  if (!to) {
    return NextResponse.json(
      { error: "כתובת יעד למייל לא הוגדרה בשרת." },
      { status: 503 },
    );
  }

  let fromEmail = normalizeEmailLike(
    process.env.RESEND_FROM_EMAIL || DEFAULT_RESEND_FROM,
  );
  if (!emailRe.test(fromEmail)) {
    fromEmail = DEFAULT_RESEND_FROM;
  }
  /** Display name matches Resend dashboard style ("Name <email>") for provider compatibility. */
  const from = `Nativ <${fromEmail}>`;

  const labels: Record<string, string> = {
    formType: "סוג טופס",
    fullName: "שם מלא",
    company: "חברה",
    role: "תפקיד",
    phone: "טלפון",
    email: "אימייל",
    description: "תיאור",
    issueType: "סוג פנייה",
  };

  const displayFields: Record<string, string | undefined> = {
    [labels.formType]: formType,
    [labels.fullName]: fullName,
    [labels.company]: company,
    [labels.role]: role || undefined,
    [labels.phone]: phone,
    [labels.email]: email,
    [labels.description]: description,
    [labels.issueType]: issueType || undefined,
  };

  const subject =
    formType === "Contact"
      ? `פנייה חדשה — צור קשר — ${fullName}`
      : `פנייה חדשה — תמיכה — ${fullName}`;

  const resend = new Resend(apiKey);
  console.log("[send-email] sending", { from, to });

  const { error } = await resend.emails.send({
    from,
    to: [to],
    replyTo: email,
    subject,
    html: buildHtmlBody(displayFields),
  });

  if (error) {
    console.error("[send-email]", error);
    return NextResponse.json(
      { error: "שליחת המייל נכשלה. נסו שוב מאוחר יותר." },
      { status: 502 },
    );
  }

  return NextResponse.json({ ok: true });
}
