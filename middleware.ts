import { NextResponse, type NextRequest } from "next/server";

const AUTH_COOKIE = "auth";
const AUTH_PAYLOAD = "ok";

async function hmacHex(secret: string, value: string): Promise<string> {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    enc.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(value));
  return Array.from(new Uint8Array(sig))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}

export async function middleware(req: NextRequest) {
  const secret = process.env.APP_SESSION_SECRET;
  if (!secret) {
    return new NextResponse("APP_SESSION_SECRET is not configured", {
      status: 500,
    });
  }

  const token = req.cookies.get(AUTH_COOKIE)?.value;
  const expected = await hmacHex(secret, AUTH_PAYLOAD);
  const ok = !!token && timingSafeEqual(token, expected);

  if (!ok) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.search = "";
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!login|about|pricing|faq|contact|support|api/login|api/logout|api/auth|api/send-email|_next/static|_next/image|favicon.ico|branding).*)",
  ],
};
