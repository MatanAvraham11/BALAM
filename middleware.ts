import { NextResponse, type NextRequest } from "next/server";

// TEMP: Auth removed for testing. MUST restore before merging to main.
export async function middleware(_req: NextRequest) {
  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!login|about|pricing|faq|contact|support|api/login|api/logout|api/auth|api/send-email|_next/static|_next/image|favicon.ico|branding).*)",
  ],
};
