import { NextResponse, type NextRequest } from "next/server";

// TEMP (V.4.1): אימות מבוטל לבדיקות — כניסה ישירה ללא סיסמה. להחזיר לפני מיזוג ל-main.
// TEMP: Auth bypass for V.4.1 preview. MUST restore before merging to main.
export async function middleware(_req: NextRequest) {
  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!login|about|pricing|faq|contact|support|api/login|api/logout|api/auth|api/send-email|_next/static|_next/image|favicon.ico|branding).*)",
  ],
};
