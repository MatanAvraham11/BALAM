import { NextRequest } from "next/server";
import { proxyRafaelRequest } from "../rafaelProxy";

/**
 * Rafael ZIP / PLR: always handled by this route.
 *
 * - `RAFAEL_BOM_WORKER_URL` — Docker worker (same worker, supports /api/rafael-zip).
 * - `PYDEV_API_BASE_URL` — local `next dev` + uvicorn on another port.
 * - Otherwise — same-origin `/api/internal/rafael-zip` → Vercel Python.
 */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  return proxyRafaelRequest(request, {
    endpoint: "rafael-zip",
    missingDevConfigError:
      "Rafael ZIP: ב־next dev יש להריץ את ה־API ב־Python (uvicorn) ולהגדיר PYDEV_API_BASE_URL, או להשתמש ב־vercel dev.",
  });
}
