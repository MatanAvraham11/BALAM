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

# Vercel runs this file with import path that does not include the api/ directory,
# so sibling modules (parse_balam, parse_drawing) are not found unless we add it.
_API_DIR = os.path.dirname(os.path.abspath(__file__))
if _API_DIR not in sys.path:
    sys.path.insert(0, _API_DIR)

import eval_type_backport  # noqa: F401  # Pydantic needs this on Py<3.10 for PEP604 unions in parsers

import pandas as pd
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from parse_balam import PurchaseOrder, extract_text_from_pdf, parse_balam_text
from fai_parser import items_to_csv, run_fai

app = FastAPI()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _session_secret_value() -> str:
    """Return stripped APP_SESSION_SECRET, or empty if unset."""
    return (os.environ.get("APP_SESSION_SECRET") or "").strip()


def _hmac_sign_payload(secret: str, value: str) -> str:
    if not secret:
        raise ValueError("session secret is empty")
    return hmac.new(
        secret.encode("utf-8"),
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


_AUTH_COOKIE = "auth"
_AUTH_PAYLOAD = "ok"


def _verify_cookie(token: str | None) -> bool:
    if not token:
        return False
    secret = _session_secret_value()
    if not secret:
        return False
    try:
        expected = _hmac_sign_payload(secret, _AUTH_PAYLOAD)
    except (TypeError, ValueError):
        return False
    if len(token) != len(expected):
        return False
    return hmac.compare_digest(token, expected)


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
    a = str(entered or "").strip()
    b = str(expected or "").strip()
    if len(a) != len(b):
        return False
    return secrets.compare_digest(a, b)


@app.post("/api/login")
async def login(request: Request, body: LoginBody) -> JSONResponse:
    # Temporary: confirm env binding in Vercel (never log the value)
    print(
        "[login] APP_PASSWORD set="
        f"{bool(os.environ.get('APP_PASSWORD'))!s}; "
        f"APP_SESSION_SECRET set="
        f"{bool((os.environ.get('APP_SESSION_SECRET') or '').strip())!s}; "
        f"Content-Type={request.headers.get('content-type', 'missing')!r}; "
        f"password len={len(str(body.password))} (Pydantic)",
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

    if not _passwords_match(str(body.password), expected):
        raise HTTPException(status_code=401, detail="סיסמה שגויה")

    session_secret = _session_secret_value()
    if not session_secret:
        print(
            "[login] APP_SESSION_SECRET empty after strip; cannot set auth cookie",
            file=sys.stderr,
            flush=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Server configuration: APP_SESSION_SECRET is not set",
        )

    resp = JSONResponse(content={"ok": True})
    try:
        cookie_value = _hmac_sign_payload(session_secret, _AUTH_PAYLOAD)
    except (TypeError, ValueError) as e:
        print(
            f"[login] cookie signing error: {type(e).__name__}: {e}",
            file=sys.stderr,
            flush=True,
        )
        raise HTTPException(
            status_code=500, detail="Server configuration: failed to set session cookie"
        ) from e

    resp.set_cookie(
        key=_AUTH_COOKIE,
        value=cookie_value,
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
        result, annotated_pdf_bytes = run_fai(tmp_path)

        items_dicts = [
            {
                "balloon_number": it.balloon_number,
                "text": it.text,
                "dimension_type": it.dimension_type,
                "tolerance": it.tolerance,
            }
            for it in result.items
        ]

        csv_str = items_to_csv(result.items)
        csv_bytes = csv_str.encode("utf-8-sig")

        original_name = file.filename or "drawing"
        base = original_name.rsplit(".", 1)[0]

        return JSONResponse(content={
            "items": items_dicts,
            "csv_base64": base64.b64encode(csv_bytes).decode(),
            "csv_filename": f"{base}_fai.csv",
            "annotated_pdf_base64": base64.b64encode(annotated_pdf_bytes).decode(),
            "annotated_pdf_filename": f"{base}_annotated.pdf",
        })
    finally:
        os.unlink(tmp_path)
