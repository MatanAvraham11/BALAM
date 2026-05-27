import { NextRequest, NextResponse } from "next/server";

/**
 * Rafael ZIP / PLR: always handled by this route.
 *
 * - `RAFAEL_BOM_WORKER_URL` — Docker worker (same worker, supports /api/rafael-zip).
 * - `PYDEV_API_BASE_URL` — local `next dev` + uvicorn on another port.
 * - Otherwise — same-origin `/api/internal/rafael-zip` → Vercel Python.
 */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function upstreamZipUrl(request: NextRequest): string | null {
  const worker = process.env["RAFAEL_BOM_WORKER_URL"]?.trim();
  if (worker) {
    return `${worker.replace(/\/$/, "")}/api/rafael-zip`;
  }
  const pydev = process.env["PYDEV_API_BASE_URL"]?.trim();
  if (pydev) {
    return `${pydev.replace(/\/$/, "")}/api/internal/rafael-zip`;
  }
  if (
    process.env.NODE_ENV === "development" &&
    process.env.VERCEL !== "1"
  ) {
    return null;
  }
  const origin = new URL(request.url).origin;
  return `${origin}/api/internal/rafael-zip`;
}

export async function POST(request: NextRequest) {
  const url = upstreamZipUrl(request);
  if (!url) {
    return NextResponse.json(
      {
        error:
          "Rafael ZIP: ב־next dev יש להריץ את ה־API ב־Python (uvicorn) ולהגדיר PYDEV_API_BASE_URL, או להשתמש ב־vercel dev.",
      },
      { status: 503 },
    );
  }
  const cookie = request.headers.get("cookie") ?? "";
  let body: FormData;
  try {
    body = await request.formData();
  } catch {
    return NextResponse.json(
      { detail: "Expected multipart form with file and parent_part_number fields" },
      { status: 400 },
    );
  }

  const upstream = await fetch(url, {
    method: "POST",
    headers: { cookie },
    body,
  });

  const ct =
    upstream.headers.get("content-type") ?? "application/json; charset=utf-8";
  const buf = await upstream.arrayBuffer();
  return new NextResponse(buf, {
    status: upstream.status,
    headers: { "content-type": ct },
  });
}
