import { NextRequest } from "next/server";
import { proxyRafaelRequest } from "../rafaelProxy";

/**
 * Rafael BOM: always handled by this route.
 *
 * - `RAFAEL_BOM_WORKER_URL` — optional Docker/Python worker, e.g. Fly.io URL.
 * - `PYDEV_API_BASE_URL` — local `next dev` + uvicorn on another port (see docs).
 * - Otherwise — same-origin `/api/internal/rafael-bom` → Vercel Python.
 */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  return proxyRafaelRequest(request, {
    endpoint: "rafael-bom",
    missingDevConfigError:
      "Rafael: ב־next dev יש להריץ את ה־API ב־Python (uvicorn) ולהגדיר PYDEV_API_BASE_URL, או להשתמש ב־vercel dev.",
  });
}
