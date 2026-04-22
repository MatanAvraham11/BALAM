"""
Vercel Python Serverless entry point.

Single FastAPI app exposing:
  POST /api/login
  POST /api/logout
  GET  /api/auth
  POST /api/balam
  POST /api/drawing

All routes are funnelled here via vercel.json rewrite.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import os
import secrets
import sys
import tempfile
from typing import Any

import eval_type_backport  # noqa: F401  # Pydantic needs this on Py<3.10 for PEP604 unions in parsers

import pandas as pd
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from parse_balam import PurchaseOrder, extract_text_from_pdf, parse_balam_text
from parse_drawing import (
    DrawingAnalysis,
    analyze_full_drawing,
    annotate_pdf,
    dimensions_to_csv_string,
    get_all_dimensions,
)

app = FastAPI()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _session_secret() -> str:
    s = os.environ.get("APP_SESSION_SECRET", "")
    if not s:
        raise RuntimeError("APP_SESSION_SECRET is not set")
    return s


def _sign(value: str) -> str:
    return hmac.new(
        _session_secret().encode(),
        value.encode(),
        hashlib.sha256,
    ).hexdigest()


_AUTH_COOKIE = "auth"
_AUTH_PAYLOAD = "ok"


def _verify_cookie(token: str | None) -> bool:
    if not token:
        return False
    return hmac.compare_digest(token, _sign(_AUTH_PAYLOAD))


def _require_auth(request: Request) -> None:
    token = request.cookies.get(_AUTH_COOKIE)
    if not _verify_cookie(token):
        raise HTTPException(status_code=401, detail="Unauthorized")


# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------


def _http_exc_body(exc: HTTPException) -> dict[str, Any]:
    d = exc.detail
    if isinstance(d, str):
        return {"detail": d}
    if isinstance(d, (list, dict)):
        return {"detail": d}
    return {"detail": str(d)}


@app.exception_handler(Exception)
async def _global_exc_handler(_request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content=_http_exc_body(exc),
        )
    return JSONResponse(
        status_code=500,
        content={"error": str(exc)},
    )


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

class LoginBody(BaseModel):
    """JSON body: {\"password\": \"...\"} (Content-Type: application/json)."""

    password: str


def _app_password() -> str:
    return (os.environ.get("APP_PASSWORD") or "").strip()


def _passwords_match(entered: str, expected: str) -> bool:
    a, b = entered.strip(), expected.strip()
    if len(a) != len(b):
        return False
    return secrets.compare_digest(a, b)


@app.post("/api/login")
async def login(request: Request, body: LoginBody) -> JSONResponse:
    # Temporary: confirm env binding in Vercel (never log the value)
    print(
        "[login] APP_PASSWORD in os.environ: "
        f"{bool(os.environ.get('APP_PASSWORD'))!s}; "
        f"Content-Type={request.headers.get('content-type', 'missing')!r}; "
        f"password field len={len(body.password)} (after Pydantic parse)",
        file=sys.stderr,
        flush=True,
    )

    expected = _app_password()
    if not expected:
        print(
            "[login] APP_PASSWORD empty/whitespace-only after strip",
            file=sys.stderr,
            flush=True,
        )
        raise HTTPException(
            status_code=500, detail="Server configuration: APP_PASSWORD is not set"
        )

    if not _passwords_match(body.password, expected):
        raise HTTPException(status_code=401, detail="סיסמה שגויה")

    resp = JSONResponse(content={"ok": True})
    resp.set_cookie(
        key=_AUTH_COOKIE,
        value=_sign(_AUTH_PAYLOAD),
        httponly=True,
        samesite="lax",
        secure=True,
        path="/",
    )
    return resp


@app.post("/api/logout")
async def logout() -> JSONResponse:
    resp = JSONResponse(content={"ok": True})
    resp.delete_cookie(key=_AUTH_COOKIE, path="/")
    return resp


@app.get("/api/auth")
async def auth_check(request: Request) -> JSONResponse:
    _require_auth(request)
    return JSONResponse(content={"ok": True})


# ---------------------------------------------------------------------------
# POST /api/balam
# ---------------------------------------------------------------------------

@app.post("/api/balam")
async def balam_endpoint(request: Request, file: UploadFile) -> JSONResponse:
    _require_auth(request)

    contents = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(contents)
        tmp_path = tmp.name

    try:
        text = extract_text_from_pdf(tmp_path)
        order: PurchaseOrder = parse_balam_text(text)

        rows = [
            {
                'מק"ט ספק': item.supplier_sku,
                "כמות נדרשת": item.required_quantity,
                "הוצאה": item.revision,
            }
            for item in order.line_items
        ]
        df = pd.DataFrame(rows)

        df = (
            df.groupby(['מק"ט ספק', "הוצאה"], as_index=False, sort=False)
            .agg({"כמות נדרשת": "sum"})
        )
        df.insert(0, "מספר", range(1, len(df) + 1))
        df = df[["מספר", 'מק"ט ספק', "כמות נדרשת", "הוצאה"]]

        aggregated_rows: list[dict[str, Any]] = df.to_dict(orient="records")

        original_name = file.filename or "output"
        csv_basename = original_name.rsplit(".", 1)[0] + ".csv"

        buf = io.StringIO()
        buf.write(f'מספר בל"מ: {order.balam_number}\n')
        buf.write(f"קניין: {order.buyer_name}\n\n")
        df.to_csv(buf, index=False)
        csv_bytes = buf.getvalue().encode("utf-8-sig")

        return JSONResponse(content={
            "balam_number": order.balam_number,
            "buyer_name": order.buyer_name,
            "aggregated_rows": aggregated_rows,
            "csv_base64": base64.b64encode(csv_bytes).decode(),
            "csv_filename": csv_basename,
        })
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# POST /api/drawing
# ---------------------------------------------------------------------------

@app.post("/api/drawing")
async def drawing_endpoint(request: Request, file: UploadFile) -> JSONResponse:
    _require_auth(request)

    contents = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(contents)
        tmp_path = tmp.name

    try:
        analysis: DrawingAnalysis = analyze_full_drawing(tmp_path)
        all_dims = get_all_dimensions(analysis)

        dimensions = [
            {
                "number": d.number,
                "dimension_type": d.dimension_type,
                "value": d.value,
            }
            for d in all_dims
        ]

        csv_str = dimensions_to_csv_string(analysis)
        csv_bytes = csv_str.encode("utf-8-sig")

        annotated_pdf_bytes = annotate_pdf(tmp_path, analysis)

        original_name = file.filename or "drawing"
        base = original_name.rsplit(".", 1)[0]

        return JSONResponse(content={
            "drawing_title": analysis.drawing_title,
            "part_number": analysis.part_number,
            "dimensions": dimensions,
            "csv_base64": base64.b64encode(csv_bytes).decode(),
            "csv_filename": f"{base}_dimensions.csv",
            "annotated_pdf_base64": base64.b64encode(annotated_pdf_bytes).decode(),
            "annotated_pdf_filename": f"{base}_annotated.pdf",
        })
    finally:
        os.unlink(tmp_path)
