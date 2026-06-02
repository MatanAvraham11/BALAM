import { NextRequest, NextResponse } from "next/server";

const MAX_MULTIPART_BYTES = 51 * 1024 * 1024;

type RafaelProxyOptions = {
  endpoint: "rafael-bom" | "rafael-zip";
  missingDevConfigError: string;
};

class PayloadTooLargeError extends Error {}

function upstreamRafaelUrl(
  request: NextRequest,
  endpoint: RafaelProxyOptions["endpoint"],
): string | null {
  const worker = process.env["RAFAEL_BOM_WORKER_URL"]?.trim();
  if (worker) {
    return `${worker.replace(/\/$/, "")}/api/${endpoint}`;
  }
  const pydev = process.env["PYDEV_API_BASE_URL"]?.trim();
  if (pydev) {
    return `${pydev.replace(/\/$/, "")}/api/internal/${endpoint}`;
  }
  if (
    process.env.NODE_ENV === "development" &&
    process.env.VERCEL !== "1"
  ) {
    return null;
  }
  const origin = new URL(request.url).origin;
  return `${origin}/api/internal/${endpoint}`;
}

async function readRequestBody(request: NextRequest): Promise<ArrayBuffer> {
  const contentLength = Number(request.headers.get("content-length"));
  if (Number.isFinite(contentLength) && contentLength > MAX_MULTIPART_BYTES) {
    throw new PayloadTooLargeError();
  }

  const reader = request.body?.getReader();
  if (!reader) return new ArrayBuffer(0);

  const chunks: Uint8Array[] = [];
  let totalBytes = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    totalBytes += value.byteLength;
    if (totalBytes > MAX_MULTIPART_BYTES) {
      await reader.cancel();
      throw new PayloadTooLargeError();
    }
    chunks.push(value);
  }

  const body = new Uint8Array(totalBytes);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return body.buffer as ArrayBuffer;
}

export async function proxyRafaelRequest(
  request: NextRequest,
  options: RafaelProxyOptions,
) {
  const url = upstreamRafaelUrl(request, options.endpoint);
  if (!url) {
    return NextResponse.json(
      { error: options.missingDevConfigError },
      { status: 503 },
    );
  }

  const contentType = request.headers.get("content-type") ?? "";
  if (!contentType.toLowerCase().startsWith("multipart/form-data")) {
    return NextResponse.json(
      { detail: "Expected multipart form with file field" },
      { status: 400 },
    );
  }

  let body: ArrayBuffer;
  try {
    body = await readRequestBody(request);
  } catch (error) {
    if (error instanceof PayloadTooLargeError) {
      return NextResponse.json(
        { detail: "הקובץ גדול מדי. יש להעלות כל קובץ עד 50MB." },
        { status: 413 },
      );
    }
    throw error;
  }

  const upstream = await fetch(url, {
    method: "POST",
    headers: {
      "content-type": contentType,
      cookie: request.headers.get("cookie") ?? "",
    },
    body,
  });

  const responseContentType =
    upstream.headers.get("content-type") ?? "application/json; charset=utf-8";
  return new NextResponse(await upstream.arrayBuffer(), {
    status: upstream.status,
    headers: { "content-type": responseContentType },
  });
}
